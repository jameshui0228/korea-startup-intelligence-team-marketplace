"""Bounded read-only adapters. Never emit credentials, raw error bodies or full articles."""
import hashlib
import json
import math
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import timedelta
from pathlib import Path
from .model import KST, assets, clean, credentials, now, observation, stamp


class FetchError(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward credentials to a redirect target.
        raise FetchError("redirect_refused")


ALLOWED_HOSTS = {"naverapihub.apigw.ntruss.com", "trends.google.com", "news.google.com",
                 "www.googleapis.com", "www.bizinfo.go.kr", "api.github.com", "hn.algolia.com", "api.x.com",
                 "kosis.kr", "api.crossref.org"}


def fetch(url, headers=None, payload=None, timeout=12):
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in ALLOWED_HOSTS or parts.username or parts.port:
        raise FetchError("unsupported_endpoint")
    headers = {"User-Agent": "KoreaStartupIntelligence/0.6.1 (personal research; metadata only)",
               "Accept": "application/json, application/rss+xml, application/xml", **(headers or {})}
    body = json.dumps(payload).encode() if payload is not None else None
    if body is not None:
        headers["Content-Type"] = "application/json"
    try:
        request = urllib.request.Request(url, data=body, headers=headers)
        verify_paths = ssl.get_default_verify_paths()
        os_bundle = Path("/etc/ssl/cert.pem")
        context = ssl.create_default_context(cafile=str(os_bundle) if not verify_paths.cafile and os_bundle.is_file() else None)
        with urllib.request.build_opener(NoRedirect, urllib.request.HTTPSHandler(context=context)).open(request, timeout=timeout) as response:
            raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise FetchError("response_too_large")
            # Persist only response hash, counts and timing, not raw provider text or auth-bearing URLs.
            return raw, {"response_sha256": hashlib.sha256(raw).hexdigest(),
                         "bytes": len(raw), "status": response.status}
    except urllib.error.HTTPError as exc:
        raise FetchError(f"http_{exc.code}") from None
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, ssl.SSLCertVerificationError):
            raise FetchError("tls_certificate_error") from None
        raise FetchError("network_or_timeout") from None
    except (OSError, TimeoutError):
        raise FetchError("network_or_timeout") from None


def hub_headers(keys):
    return {"X-NCP-APIGW-API-KEY-ID": keys["NAVER_HUB_CLIENT_ID"],
            "X-NCP-APIGW-API-KEY": keys["NAVER_HUB_CLIENT_SECRET"]}


def decode_json(raw):
    result = json.loads(raw)
    if not isinstance(result, dict) or any(k in result for k in ("error", "errorCode", "errId")):
        raise FetchError("provider_error_or_schema")
    return result


def naver_search(source, topic, keys, timeout):
    endpoint = {"naver_news": "news", "naver_blog": "blog", "naver_cafe": "cafearticle"}[source]
    url = "https://naverapihub.apigw.ntruss.com/search/v1/" + endpoint + "?" + urllib.parse.urlencode(
        {"query": topic, "display": 20, "start": 1, "sort": "date", "format": "json"})
    raw, receipt = fetch(url, hub_headers(keys), timeout=timeout)
    result = decode_json(raw)
    if not isinstance(result.get("items"), list):
        raise FetchError("items_missing")
    rows = []
    for item in result["items"]:
        event = item.get("pubDate") or item.get("postdate")
        if event and len(event) == 8 and event.isdigit():
            event = f"{event[:4]}-{event[4:6]}-{event[6:]}"
        url = item.get("originallink") or item.get("link")
        if not url or not item.get("title"):
            continue
        rows.append(observation(source, "article" if endpoint == "news" else "community_post", topic,
                                item["title"], url, event,
                                limitations=["search_selection_bias", "not_population_demand", "source_content_untrusted"],
                                # Title only by default. Raw passages / handles / user text are not archived.
                                content_scope="search_title_and_link"))
    receipt["provider_total_not_search_volume"] = result.get("total")
    receipt["truncated_to"] = 20
    return rows, receipt


def naver_trend(topic, keys, timeout):
    end = now().astimezone(KST).date() - timedelta(days=1)
    body = {"startDate": str(end - timedelta(days=83)), "endDate": str(end), "timeUnit": "date",
            "keywordGroups": [{"groupName": topic, "keywords": [topic]}]}
    raw, receipt = fetch("https://naverapihub.apigw.ntruss.com/search-trend/v1/search",
                         hub_headers(keys), body, timeout)
    result = decode_json(raw)
    if not isinstance(result.get("results"), list) or not result["results"]:
        raise FetchError("series_missing")
    data = result["results"][0].get("data")
    if not isinstance(data, list):
        raise FetchError("series_missing")
    series = [{"date": item["period"], "value": float(item["ratio"])} for item in data]
    row = observation("naver_trend", "series", topic, f"{topic} 네이버 검색 관심도",
                      "https://datalab.naver.com/keyword/trendSearch.naver", str(end), series=series,
                      metrics={"unit": "relative_index_0_100", "start": body["startDate"], "end": body["endDate"],
                               "normalization_scope": "one_request_one_keyword_84days", "time_unit": "date"},
                      content_scope="aggregate_search_index",
                      origin_key="naver-search:" + topic,
                      limitations=["relative_not_absolute", "no_seasonal_adjustment", "keyword_selection_bias"])
    return [row], receipt


def safe_xml(raw):
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise FetchError("xml_entities_refused")
    return ET.fromstring(raw)


def google_trends(topic, timeout):
    if topic not in ("KR", "JP", "US", "SG", "GB", "IN"):
        raise FetchError("country_not_configured")
    country = topic
    url = "https://trends.google.com/trending/rss?geo=" + country
    raw, receipt = fetch(url, timeout=timeout)
    root = safe_xml(raw)
    rows = []
    for item in root.findall("./channel/item")[:50]:
        title = item.findtext("title")
        if not title:
            continue
        traffic = next((el.text for el in item if el.tag.endswith("approx_traffic")), None)
        evidence_url = "https://trends.google.com/trending?geo=" + country
        rows.append(observation("google_trends_rss", "search_spike", title, title, evidence_url,
                                item.findtext("pubDate"), geography=country,
                                metrics={"traffic_bucket": traffic}, origin_key="google-search:" + country + ":" + title,
                                content_scope="public_trending_feed",
                                limitations=["selected_news_related_spike", "not_a_time_series", "not_purchase_demand"]))
    if root.tag != "rss":
        raise FetchError("rss_schema_changed")
    return rows, receipt


def google_news(topic, timeout):
    query = urllib.parse.urlencode({"q": topic + " when:7d", "hl": "ko", "gl": "KR", "ceid": "KR:ko"})
    raw, receipt = fetch("https://news.google.com/rss/search?" + query, timeout=timeout)
    root = safe_xml(raw)
    if root.tag != "rss":
        raise FetchError("rss_schema_changed")
    rows = []
    for item in root.findall("./channel/item")[:20]:
        if not item.findtext("link"):
            continue
        publisher = item.find("source")
        rows.append(observation("google_news_rss", "article", topic, item.findtext("title"), item.findtext("link"),
                                item.findtext("pubDate"), publisher=clean(publisher.text) if publisher is not None else "unknown",
                                limitations=["aggregator_origin_not_resolved", "news_syndication", "selected_results"],
                                content_scope="rss_title_and_link"))
    return rows, receipt


def youtube(topic, keys, timeout):
    params = {"part": "snippet", "q": topic, "type": "video", "maxResults": 10, "order": "date",
              "regionCode": "KR", "relevanceLanguage": "ko", "publishedAfter": stamp(now() - timedelta(days=14)),
              "key": keys["YOUTUBE_API_KEY"]}
    raw, receipt = fetch("https://www.googleapis.com/youtube/v3/search?" + urllib.parse.urlencode(params), timeout=timeout)
    result = decode_json(raw)
    if not isinstance(result.get("items"), list):
        raise FetchError("items_missing")
    rows = []
    for item in result["items"]:
        video = item.get("id", {}).get("videoId")
        if not video:
            continue
        info = item["snippet"]
        rows.append(observation("youtube", "social_post", topic, info["title"], "https://www.youtube.com/watch?v=" + video,
                                info.get("publishedAt"), geography="KR_query_not_audience",
                                limitations=["no_views_fetched", "not_representative", "region_query_not_audience"]))
    return rows, receipt


def youtube_uploads(playlist_id, keys, timeout):
    """One page of a configured uploads playlist. No hidden channel lookup."""
    if not re.fullmatch(r'UU[A-Za-z0-9_-]{22}', playlist_id):
        raise FetchError('youtube_uploads_playlist_id_required')
    params = {'part': 'snippet,contentDetails', 'playlistId': playlist_id, 'maxResults': 20, 'key': keys['YOUTUBE_API_KEY']}
    raw, receipt = fetch('https://www.googleapis.com/youtube/v3/playlistItems?' + urllib.parse.urlencode(params), timeout=timeout)
    result = decode_json(raw)
    if not isinstance(result.get('items'), list):
        raise FetchError('youtube_uploads_schema_changed')
    rows = []
    for item in result['items']:
        info, details = item.get('snippet', {}), item.get('contentDetails', {})
        video = details.get('videoId')
        if not isinstance(video, str) or not re.fullmatch(r'[A-Za-z0-9_-]{11}', video):
            raise FetchError('youtube_uploads_schema_changed')
        rows.append(observation('youtube_uploads', 'social_post', 'uploads:' + playlist_id,
            info.get('title'), 'https://www.youtube.com/watch?v=' + video, details.get('videoPublishedAt'),
            geography='unknown_audience', channel_id=info.get('videoOwnerChannelId'), video_format='UNKNOWN',
            limitations=['selected_channel_not_platform_census', 'first_page_max20', 'metadata_not_content_review', 'not_demand']))
    receipt.update({'coverage': 'configured_uploads_playlist_first_page_max20', 'has_more': bool(result.get('nextPageToken'))})
    return rows, receipt


def youtube_comment_sample(video_id, keys, timeout=12):
    """One bounded page for explicit review; discard author fields and raw payload."""
    if not isinstance(video_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id):
        raise FetchError('youtube_video_id_required')
    params = {'part': 'snippet', 'videoId': video_id, 'maxResults': 20, 'order': 'time',
              'textFormat': 'plainText', 'key': keys['YOUTUBE_API_KEY']}
    raw, receipt = fetch('https://www.googleapis.com/youtube/v3/commentThreads?' + urllib.parse.urlencode(params), timeout=timeout)
    result = decode_json(raw)
    if not isinstance(result.get('items'), list) or len(result['items']) > 20:
        raise FetchError('youtube_comments_schema_changed')
    samples = []
    for item in result['items']:
        try:
            info = item['snippet']['topLevelComment']['snippet']
            value = info['textDisplay']
        except (KeyError, TypeError):
            raise FetchError('youtube_comments_schema_changed') from None
        if not isinstance(value, str):
            raise FetchError('youtube_comments_schema_changed')
        value = re.sub(r'https?://\S+|[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}|@[\w.]+|01[016789][- ]?\d{3,4}[- ]?\d{4}', '[redacted]', value)
        samples.append({'sample_index': len(samples)+1, 'excerpt': clean(value)[:240],
                        'published_at': info.get('publishedAt'), 'truncated': len(value) > 240})
    receipt.update({'sample_count': len(samples), 'has_more': bool(result.get('nextPageToken')),
                    'coverage': 'latest_first_page_top_level_only_max20', 'author_fields_retained': False})
    return samples, receipt


def youtube_statistics(video_ids, keys, timeout):
    """One explicitly budgeted request; no hidden searches, comments or profiles."""
    ids = video_ids.split(",")
    if not 1 <= len(ids) <= 20 or len(ids) != len(set(ids)) or any(not re.fullmatch(r"[A-Za-z0-9_-]{11}", i) for i in ids):
        raise FetchError("youtube_video_ids_required_max20")
    params = {"part": "snippet,statistics", "id": ",".join(ids), "key": keys["YOUTUBE_API_KEY"]}
    raw, receipt = fetch("https://www.googleapis.com/youtube/v3/videos?" + urllib.parse.urlencode(params), timeout=timeout)
    result = decode_json(raw)
    if not isinstance(result.get("items"), list):
        raise FetchError("video_statistics_schema_changed")
    rows = []
    for item in result["items"]:
        if not isinstance(item, dict) or item.get("id") not in ids or not isinstance(item.get("statistics"), dict):
            raise FetchError("video_statistics_schema_changed")
        metrics = {"metric_definition": "youtube_play_start_views_since_2026-08-24",
                   "measurement_at": stamp(), "unit": "cumulative_count_not_unique_people"}
        for external, internal in (("viewCount", "views_play_start_20260824_snapshot"),
                                   ("likeCount", "likes_snapshot"), ("commentCount", "comment_count_snapshot")):
            value = item["statistics"].get(external)
            if value is None:
                continue
            if not re.fullmatch(r"[0-9]{1,20}", str(value)):
                raise FetchError("invalid_video_counter")
            metrics[internal] = int(value)
        info = item.get("snippet", {})
        if not isinstance(info, dict):
            raise FetchError("video_statistics_schema_changed")
        rows.append(observation("youtube_stats", "social_metric", "youtube:" + item["id"], info.get("title"),
            "https://www.youtube.com/watch?v=" + item["id"], info.get("publishedAt"),
            geography="unknown_audience", metrics=metrics, content_scope="public_video_metadata_and_aggregate_counters",
            limitations=["selected_videos_not_platform_census", "cumulative_views_not_unique_people_or_demand",
                         "view_definition_changed_2026-08-24_do_not_bridge_old_definition", "no_comment_text_or_user_profiles_stored"]))
    receipt.update({"requested_video_count": len(ids), "missing_video_count": len(set(ids) - {i["id"] for i in result["items"]}),
                    "quota_units_documented": 1, "coverage": "selected_public_video_ids_only"})
    return rows, receipt


def bizinfo(keys, timeout):
    query = urllib.parse.urlencode({"crtfcKey": keys["BIZINFO_API_KEY"], "dataType": "json",
                                    "searchCnt": 30, "pageUnit": 30, "pageIndex": 1})
    raw, receipt = fetch("https://www.bizinfo.go.kr/uss/rss/bizinfoApi.do?" + query, timeout=timeout)
    result = decode_json(raw)
    items = result.get("jsonArray", {}).get("item")
    if not isinstance(items, list):
        raise FetchError("grant_schema_changed")
    rows = []
    for item in items[:30]:
        url = item.get("link") or item.get("pblancUrl")
        if not url:
            continue
        url = urllib.parse.urljoin("https://www.bizinfo.go.kr", url)
        rows.append(observation("bizinfo", "grant", "지원사업", item.get("title") or item.get("pblancNm"), url,
                                item.get("pubDate") or item.get("creatPnttm"),
                                metrics={"application_period_raw": clean(item.get("reqstBeginEndDe") or item.get("reqstDt")),
                                         "eligibility": "UNKNOWN_until_original_notice_review"},
                                limitations=["bounded_first_page_only", "eligibility_not_checked", "deadline_requires_original"]))
    receipt["coverage"] = "first_page_max30_not_all_announcements"
    return rows, receipt


def kosis_registered_series(topic, keys, timeout):
    """Fetch a bounded, user-registered KOSIS series.

    The workspace stores only the registration ID and measurement definition;
    the API key remains in the private credential store.  Rows without a
    numeric value, period or provider unit are rejected instead of being
    silently interpreted.
    """
    try:
        spec = json.loads(topic)
    except (TypeError, json.JSONDecodeError):
        raise FetchError("kosis_series_config_invalid") from None
    required = ("label", "userStatsId", "prdSe", "definition", "population", "normalization")
    if not isinstance(spec, dict) or any(not isinstance(spec.get(field), str) or
                                         not spec[field].strip() for field in required):
        raise FetchError("kosis_series_config_invalid")
    if any(len(spec[field]) > 240 for field in required) or not re.fullmatch(r"[A-Za-z0-9_.+/@:-]{1,160}", spec["userStatsId"]):
        raise FetchError("kosis_series_config_invalid")
    if not re.fullmatch(r"[A-Za-z0-9]{1,8}", spec["prdSe"]):
        raise FetchError("kosis_series_config_invalid")
    periods = spec.get("latest_periods", 3)
    if type(periods) is not int or not 1 <= periods <= 12:
        raise FetchError("kosis_series_config_invalid")
    params = {"method": "getList", "apiKey": keys["KOSIS_API_KEY"],
              "userStatsId": spec["userStatsId"], "prdSe": spec["prdSe"],
              "newEstPrdCnt": periods, "format": "json", "jsonVD": "Y"}
    raw, receipt = fetch("https://kosis.kr/openapi/statisticsData.do?" + urllib.parse.urlencode(params),
                         timeout=timeout)
    try:
        result = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        raise FetchError("kosis_schema_changed") from None
    if isinstance(result, dict) and any(key in result for key in ("err", "error", "errorCode")):
        raise FetchError("provider_error_or_schema")
    if not isinstance(result, list) or len(result) > 500:
        raise FetchError("kosis_schema_changed")
    rows = []
    for item in result:
        if not isinstance(item, dict):
            raise FetchError("kosis_schema_changed")
        period = clean(item.get("PRD_DE"), 40)
        unit = clean(item.get("UNIT_NM"), 80)
        raw_value = str(item.get("DT", "")).replace(",", "").strip()
        if not period or not unit or not re.fullmatch(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", raw_value):
            continue
        value = float(raw_value)
        if not math.isfinite(value):
            continue
        table_id = clean(item.get("TBL_ID"), 80)
        org_id = clean(item.get("ORG_ID"), 80)
        table_name = clean(item.get("TBL_NM"), 160)
        item_name = clean(item.get("ITM_NM"), 160)
        if not table_id or not org_id or not table_name or not item_name:
            raise FetchError("kosis_schema_changed")
        public_url = "https://kosis.kr/statHtml/statHtml.do?" + urllib.parse.urlencode(
            {"orgId": org_id, "tblId": table_id})
        rows.append(observation("kosis", "aggregate_metric", spec["label"],
                                f"{table_name} · {item_name} · {period}", public_url,
                                metrics={"value": value},
                                measurement={"definition": spec["definition"], "unit": unit,
                                             "population": spec["population"], "period": period,
                                             "normalization": spec["normalization"],
                                             "vintage": clean(item.get("LST_CHN_DE"), 40) or "UNKNOWN"},
                                reference_period=period, geography="KR", origin_key=f"kosis:{org_id}:{table_id}:{item_name}",
                                content_scope="official_statistical_table_api",
                                limitations=["registered_table_selection", "revision_possible",
                                             "query_time_not_observation_time", "numeric_rows_only"]))
    receipt.update({"coverage": "one_registered_series_latest_periods", "configured_latest_periods": periods,
                    "provider_rows": len(result), "numeric_rows_saved": len(rows)})
    return rows, receipt


def crossref_recent(topic, timeout):
    """Retrieve a small recent-deposit sample of scholarly metadata.

    Deposit time is deliberately kept distinct from publication time.  This is
    an early technology-research prompt, never evidence of Korean demand or a
    paper's validity.
    """
    if not isinstance(topic, str) or not 1 <= len(topic) <= 120:
        raise FetchError("crossref_topic_invalid")
    since = (now() - timedelta(days=14)).date().isoformat()
    params = {"query.title": topic, "filter": "from-created-date:" + since,
              "rows": 10, "sort": "created", "order": "desc"}
    raw, receipt = fetch("https://api.crossref.org/v1/works?" + urllib.parse.urlencode(params), timeout=timeout)
    result = decode_json(raw)
    message = result.get("message")
    if result.get("status") != "ok" or not isinstance(message, dict) or not isinstance(message.get("items"), list):
        raise FetchError("crossref_schema_changed")
    rows = []
    for item in message["items"][:10]:
        if not isinstance(item, dict) or not isinstance(item.get("DOI"), str):
            continue
        titles = item.get("title")
        title = titles[0] if isinstance(titles, list) and titles and isinstance(titles[0], str) else None
        created = item.get("created", {}).get("date-time") if isinstance(item.get("created"), dict) else None
        if not title or not created:
            continue
        doi = item["DOI"].strip()
        if not doi or len(doi) > 200 or any(char.isspace() for char in doi):
            continue
        rows.append(observation("crossref_recent", "paper", topic, title,
                                "https://doi.org/" + urllib.parse.quote(doi, safe="/():._-"), created,
                                geography="global_metadata", publisher=clean(item.get("publisher"), 160) or "unknown",
                                origin_key="crossref-doi:" + doi.lower(),
                                metrics={"is_referenced_by_count_snapshot": item.get("is-referenced-by-count")},
                                deposited_at=created, published_parts=item.get("published"), work_type=item.get("type"),
                                content_scope="deposited_bibliographic_metadata",
                                limitations=["deposit_date_not_publication_date", "query_sample_max10",
                                             "publisher_metadata_not_peer_review_validation", "global_not_korean_demand",
                                             "citation_snapshot_not_growth_or_commercial_adoption"]))
    receipt.update({"coverage": "title_query_recent_deposits_first10", "provider_total_results": message.get("total-results"),
                    "saved_items": len(rows), "date_basis": "crossref_created_deposit_time"})
    return rows, receipt


def collect(source, topic, keys, timeout):
    if source == 'youtube_uploads':
        return youtube_uploads(topic, keys, timeout)
    if source == "github_new":
        return github_new(topic, timeout)
    if source == "hackernews":
        return hackernews(topic, timeout)
    if source in ("naver_news", "naver_blog", "naver_cafe"):
        return naver_search(source, topic, keys, timeout)
    if source == "naver_trend":
        return naver_trend(topic, keys, timeout)
    if source == "google_trends_rss":
        return google_trends(topic, timeout)
    if source == "google_news_rss":
        return google_news(topic, timeout)
    if source == "youtube":
        return youtube(topic, keys, timeout)
    if source == "youtube_stats":
        return youtube_statistics(topic, keys, timeout)
    if source == "bizinfo":
        return bizinfo(keys, timeout)
    if source == "kosis":
        return kosis_registered_series(topic, keys, timeout)
    if source == "crossref_recent":
        return crossref_recent(topic, timeout)
    raise FetchError("adapter_not_implemented")


def github_new(topic, timeout):
    since = (now() - timedelta(days=90)).date().isoformat()
    query = urllib.parse.urlencode({"q": f"{topic} created:>{since} archived:false fork:false", "sort": "stars", "order": "desc", "per_page": 10})
    raw, receipt = fetch("https://api.github.com/search/repositories?" + query,
                         headers={"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}, timeout=timeout)
    result = decode_json(raw)
    if not isinstance(result.get("items"), list):
        raise FetchError("repository_schema_changed")
    rows = []
    for item in result["items"]:
        rows.append(observation("github_new", "repository", topic, item["full_name"], item["html_url"], item.get("created_at"),
                                geography="global", metrics={"stars_snapshot": item.get("stargazers_count"), "forks_snapshot": item.get("forks_count"),
                                                             "created_at": item.get("created_at"), "pushed_at": item.get("pushed_at"), "star_growth": None},
                                limitations=["stars_not_customers", "growth_requires_repeated_snapshots", "author_claims_unverified", "license_not_audited"]))
    receipt["total_matches"] = result.get("total_count")
    receipt["incomplete_results"] = result.get("incomplete_results")
    return rows, receipt


def hackernews(topic, timeout):
    cutoff = int((now() - timedelta(days=14)).timestamp())
    params = {"query": topic, "tags": "story", "numericFilters": f"created_at_i>{cutoff}", "hitsPerPage": 10}
    raw, receipt = fetch("https://hn.algolia.com/api/v1/search_by_date?" + urllib.parse.urlencode(params), timeout=timeout)
    result = decode_json(raw)
    if not isinstance(result.get("hits"), list):
        raise FetchError("hn_schema_changed")
    rows = []
    for item in result["hits"]:
        if not item.get("title") or not item.get("objectID"):
            continue
        rows.append(observation("hackernews", "community_post", topic, item["title"],
                                "https://news.ycombinator.com/item?id=" + item["objectID"], item.get("created_at"), geography="global",
                                metrics={"points_snapshot": item.get("points"), "comments_snapshot": item.get("num_comments")},
                                limitations=["developer_community_bias", "no_growth_series", "not_korean_demand"]))
    return rows, receipt
