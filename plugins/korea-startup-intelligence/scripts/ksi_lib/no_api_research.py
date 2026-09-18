"""Credential-free, on-demand public-web research planning.

The planner never claims that a search result was read.  It gives Codex a
bounded set of queries and an evidence contract; reviewed pages are persisted
separately through ``signal batch-import``.
"""
from __future__ import annotations

from .model import digest, stamp
from .radar import bounded_text


LANES = {
    "social_public": {
        "label": "공개 SNS·커뮤니티",
        "sources": ["instagram", "tiktok", "x", "threads", "reddit", "youtube"],
        "query": '"{topic}" (불편 OR 문제 OR 후기 OR workaround) (site:reddit.com OR site:x.com OR site:threads.net OR site:tiktok.com OR site:instagram.com)',
        "purpose": "공개 색인 범위에서 반복 문제 표현과 반례를 찾는다.",
        "preferred_origins": ["공개 원게시물", "공개 댓글 스레드", "플랫폼 공개 페이지"],
        "limitations": ["로그인·비공개·전체 피드에 접근하지 않음", "검색 색인 표본은 플랫폼 추세나 한국 대표 표본이 아님"],
    },
    "jobs": {
        "label": "채용·업무 변화",
        "sources": ["jobs"],
        "query": '"{topic}" (채용 OR 담당업무 OR 자격요건) (site:work24.go.kr OR site:jobkorea.co.kr OR site:saramin.co.kr)',
        "purpose": "새 역할·업무량·도구 요구를 원 고용주 공고에서 확인한다.",
        "preferred_origins": ["고용24 공개 공고", "기업 공식 채용 페이지", "원 고용주 공고"],
        "limitations": ["중복 게재와 채용 브랜딩 가능성", "채용 공고는 고객 수요나 실제 채용 완료의 증명이 아님"],
    },
    "patents": {
        "label": "특허",
        "sources": ["patents"],
        "query": '"{topic}" (특허 OR 출원 OR 등록) (site:kipris.or.kr OR site:plus.kipris.or.kr)',
        "purpose": "출원·공개·등록 상태와 권리자를 구분해 기술 공급 변화를 찾는다.",
        "preferred_origins": ["KIPRIS 공개 특허 원문", "특허청 공개 자료"],
        "limitations": ["출원은 등록·상용화·수요가 아님", "권리 상태와 사건일을 원문에서 재확인"],
    },
    "standards": {
        "label": "표준·인증",
        "sources": ["standards"],
        "query": '"{topic}" (표준 OR 인증 OR 개정) (site:standard.go.kr OR site:kats.go.kr)',
        "purpose": "새 표준·인증·개정이 만드는 전환 비용과 준비 업무를 확인한다.",
        "preferred_origins": ["e나라표준인증", "국가기술표준원 공고", "표준 제정기관 원문"],
        "limitations": ["초안·예고·시행 상태를 구분", "표준 변화만으로 구매 의사를 추정하지 않음"],
    },
    "papers": {
        "label": "논문·연구",
        "sources": ["papers"],
        "query": '"{topic}" (논문 OR 연구 OR 실증) (site:scienceon.kisti.re.kr OR site:doi.org OR site:crossref.org)',
        "purpose": "새 기술 가능성과 한계를 원 논문·공식 메타데이터에서 확인한다.",
        "preferred_origins": ["원 논문", "DOI 등록 원문", "KISTI ScienceON"],
        "limitations": ["발행·등록·인용일을 구분", "논문 존재는 재현성·상용성·고객 수요의 증명이 아님"],
    },
    "technology_cost": {
        "label": "기술 가격",
        "sources": ["technology_cost"],
        "query": '"{topic}" (가격 OR 요금 OR 단가 OR cost) (공식 OR pricing OR 사양)',
        "purpose": "동일 단위의 공개 공식 가격·사양 변화를 찾아 사업 가능 조건을 점검한다.",
        "preferred_origins": ["공급자 공식 가격표", "공식 조달 단가", "표준 사양서"],
        "limitations": ["할인·환율·세금·용량·품질 차이를 분리", "서로 다른 단위를 성장률로 결합하지 않음"],
    },
    "procurement": {
        "label": "조달·입찰",
        "sources": ["procurement"],
        "query": '"{topic}" (입찰 OR 사전규격 OR 낙찰 OR 제안요청) (site:g2b.go.kr OR site:pps.go.kr)',
        "purpose": "기관이 명시한 구매 요구·예산·납기와 실제 낙찰을 구분해 확인한다.",
        "preferred_origins": ["나라장터 원 공고", "조달청 공개 자료", "발주기관 제안요청서"],
        "limitations": ["공고와 계약·집행을 구분", "한 기관의 요구를 시장 전체 수요로 일반화하지 않음"],
    },
    "app_store": {
        "label": "앱스토어",
        "sources": ["app_store"],
        "query": '"{topic}" (리뷰 OR 평점 OR 업데이트) (site:play.google.com/store/apps OR site:apps.apple.com/kr)',
        "purpose": "제품 공급·업데이트와 공개 이용자 불편을 각각 확인한다.",
        "preferred_origins": ["Google Play 공개 앱 페이지", "Apple App Store 공개 앱 페이지"],
        "limitations": ["표시 순위·리뷰는 시점 표본", "리뷰어 역할·광고·조작 가능성을 확인"],
    },
    "commerce": {
        "label": "커머스·가격·품절",
        "sources": ["commerce"],
        "query": '"{topic}" (가격 OR 품절 OR 예약판매 OR 리뷰) (공식몰 OR 제조사 OR 판매처)',
        "purpose": "같은 상품·옵션의 가격, 재고, 신제품, 공개 후기 변화를 확인한다.",
        "preferred_origins": ["제조사 공식몰", "공개 판매 페이지", "가격·재고가 명시된 원문"],
        "limitations": ["검색 결과 수를 판매량으로 해석하지 않음", "옵션·배송·쿠폰·판매자 차이를 분리"],
    },
    "crowdfunding": {
        "label": "크라우드펀딩",
        "sources": ["crowdfunding"],
        "query": '"{topic}" (펀딩 OR 프리오더 OR 배송지연 OR 환불) (site:wadiz.kr OR site:kickstarter.com)',
        "purpose": "신제품·참여·후속 배송 문제를 프로젝트 원문과 업데이트에서 확인한다.",
        "preferred_origins": ["와디즈 공개 프로젝트", "프로젝트 업데이트", "플랫폼 공개 상태"],
        "limitations": ["후원액은 인식 매출·반복 구매가 아님", "광고 유입과 배송 성공을 별도 확인"],
    },
    "regulation": {
        "label": "법령·행정예고",
        "sources": ["regulation"],
        "query": '"{topic}" (입법예고 OR 행정예고 OR 시행일 OR 개정) (site:law.go.kr OR site:mooleg.go.kr OR site:epeople.go.kr)',
        "purpose": "예고·공포·시행일과 적용 대상을 공식 원문에서 구분한다.",
        "preferred_origins": ["국가법령정보센터", "국민참여입법센터", "소관 부처 공고"],
        "limitations": ["부분 검색은 법률 자문이 아님", "예고안과 현행·시행 법령을 혼동하지 않음"],
    },
    "official_statistics": {
        "label": "공식 통계",
        "sources": ["kosis", "ecos"],
        "query": '"{topic}" (통계표 OR 지표 OR 시계열) (site:kosis.kr OR site:ecos.bok.or.kr)',
        "purpose": "시장 분모와 방향을 공식 표에서 정의·단위·모집단·기간·판본과 함께 확인한다.",
        "preferred_origins": ["KOSIS 원 통계표", "한국은행 ECOS 원 통계표", "원 생산기관 공표"],
        "limitations": ["검색 결과 조각이 아닌 원 표를 확인", "공표 시점과 기준 시점·개정 판본을 구분"],
    },
}


def _fallback_topic(store):
    watched = [value.strip() for value in store.config.get("watch_topics", [])
               if isinstance(value, str) and value.strip()]
    if watched:
        return watched[0], "workspace_watch_topic"
    candidates = store.records("blue_ocean")
    if candidates:
        candidate = candidates[0]
        return (candidate.get("problem") or candidate.get("title")), "current_candidate"
    return "한국 산업 현장 반복 불편", "broad_discovery_default"


def plan(store, topic=None, lanes=None, limit=12, since_days=30):
    if topic is None:
        topic, topic_basis = _fallback_topic(store)
    else:
        topic_basis = "user_request"
    topic = bounded_text(topic, "topic", 160)
    if type(limit) is not int or not 1 <= limit <= 24:
        raise ValueError("limit은 1~24 범위여야 합니다.")
    if type(since_days) is not int or not 1 <= since_days <= 365:
        raise ValueError("since_days는 1~365 범위여야 합니다.")
    selected = list(LANES) if lanes is None else lanes
    if not isinstance(selected, list) or not selected or len(selected) > len(LANES) or \
            any(lane not in LANES for lane in selected) or len(set(selected)) != len(selected):
        raise ValueError("lane은 중복 없이 알려진 공개 웹 조사 계열을 사용하세요.")
    tasks = []
    for lane in selected[:limit]:
        spec = LANES[lane]
        tasks.append({
            "task_id": "web-" + digest([topic, lane, since_days])[:20],
            "lane": lane,
            "label": spec["label"],
            "query": spec["query"].format(topic=topic),
            "topic": topic,
            "since_days": since_days,
            "source_options": spec["sources"],
            "purpose": spec["purpose"],
            "preferred_origins": spec["preferred_origins"],
            "required_review": [
                "검색 결과가 아니라 실제 공개 원문 열기",
                "발행/사건일·원 생산자·읽은 범위·한계를 자기 말로 기록",
                "고객 발언은 실제 이용자 역할을 확인한 경우에만 speaker_role=customer",
                "광고·계절성·봇·낮은 기저·동일 보도자료 재인용 반례 확인",
            ],
            "limitations": spec["limitations"],
            "save_with": "signal batch-import --file REVIEWED_SIGNALS.json",
        })
    return {
        "mode": "on_demand_public_web",
        "generated_at": stamp(),
        "topic": topic,
        "topic_basis": topic_basis,
        "credentials_required": False,
        "scheduled_or_background_execution": False,
        "tasks": tasks,
        "unplanned_lanes": [lane for lane in selected if lane not in {task["lane"] for task in tasks}],
        "next": [
            "Codex가 tasks의 공개 웹 검색과 원문 열람을 수행",
            "실제로 읽은 자료만 signal batch-import로 원자적 접수",
            "blue-ocean run --no-refresh로 포트폴리오 재평가·다음 행동 연결",
        ],
        "boundary": "API 키 없는 공개 웹 조사 계획입니다. 검색 결과 생성은 수집·원문 검토·플랫폼 전수조사의 증명이 아닙니다.",
    }
