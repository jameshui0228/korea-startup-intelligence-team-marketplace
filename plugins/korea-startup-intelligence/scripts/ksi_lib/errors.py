"""Korean recovery guidance; never echo file errors or external response bodies."""
import json
import sqlite3


def explain(exc):
    if isinstance(exc, json.JSONDecodeError):
        return {'status': 'error', 'code': 'invalid_json', 'message': 'JSON 입력 형식을 확인하세요.',
                'next_action': f'{exc.lineno}행 {exc.colno}열 부근의 쉼표·따옴표·괄호를 확인하세요. 원문 값은 출력하지 않습니다.'}
    if isinstance(exc, sqlite3.Error):
        return {'status': 'error', 'code': 'storage_error', 'message': '저장소 작업을 완료하지 못했습니다.',
                'next_action': '동시 실행 여부·디스크 여유·DB 무결성을 확인하세요. DB를 삭제하거나 실패 작업을 자동 반복하지 마세요.'}
    if isinstance(exc, OSError):
        return {'status': 'error', 'code': 'local_file_error', 'message': '입력 파일 또는 로컬 저장 경로를 확인하세요.',
                'next_action': '파일 존재 여부·읽기/쓰기 권한·디스크 여유를 확인하세요. 비밀 파일의 내용을 출력하지 마세요.'}
    message = str(exc)
    lower = message.lower()
    categories = (
        (('revision', '편집 충돌'), 'edit_conflict', 'workbench checkout으로 최신 내용을 읽고 변경점을 병합한 뒤 해당 revision으로 저장하세요.'),
        (('evidence', '근거'), 'evidence_required', '실제로 읽은 근거 ID·읽기 범위·원문 위치를 확인하세요. 미확인은 UNKNOWN으로 남기세요.'),
        (('secret', 'credential', 'token', '키'), 'credentials_or_permission', '키 값은 출력하지 말고 비공개 설정 파일의 권한과 필요한 키 이름만 확인하세요.'),
        (('another workspace', '한도', 'limit'), 'run_or_input_limit', '동시 실행과 입력/요청 한도를 확인하세요. 한도를 우회하거나 실행을 자동 반복하지 마세요.'),
        (('date', 'time', '시각', 'deadline'), 'time_validation', '시간대·시작/종료 순서·실제 관측 시각을 확인하세요. 모르는 시각은 허용되는 경우 null로 남기세요.'),
    )
    for words, code, action in categories:
        if any(word in lower for word in words):
            return {'status': 'error', 'code': code, 'message': message, 'next_action': action}
    return {'status': 'error', 'code': 'input_validation', 'message': message,
            'next_action': '해당 명령의 입력 양식과 필수 필드·자료형을 확인하세요. workbench 기록은 template 명령으로 양식을 확인할 수 있습니다.'}
