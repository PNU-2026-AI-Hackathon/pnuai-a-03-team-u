"""Langfuse 마스킹 함수 유닛테스트.

`docs/backend/features/llm-privacy-audit.md`의 4개 redact 패턴이 실제로 잡히는지,
그리고 오탐(과목 코드 · course_id · 학점 숫자)을 안 잡는지 확인한다.
"""

from app.ai.llm.langfuse_masking import mask_data, redact_text


def test_student_id_redacted():
    # 부산대 학번은 202112345 같이 9~10자리, 앞 4자리가 입학연도.
    assert redact_text("제 학번은 202112345인데요") == "제 학번은 <STUDENT_ID>인데요"
    assert redact_text("2018123456 학생") == "<STUDENT_ID> 학생"


def test_email_redacted():
    assert redact_text("ldw2003@pusan.ac.kr로 연락주세요") == "<EMAIL>로 연락주세요"


def test_mobile_phone_redacted():
    assert redact_text("010-1234-5678") == "<PHONE>"
    assert redact_text("01012345678") == "<PHONE>"


def test_landline_redacted():
    assert redact_text("051-510-1234로 문의") == "<PHONE>로 문의"
    assert redact_text("02-1234-5678") == "<PHONE>"


def test_no_false_positive_on_short_numbers():
    # course_id, department_id, 학점, credit_hour 등 짧은 정수는 그대로 통과해야 한다.
    assert redact_text("course_id=1234, 학점=3") == "course_id=1234, 학점=3"
    # 8자리 정수(연도 앵커에 안 걸림)는 통과.
    assert redact_text("주문번호 12345678") == "주문번호 12345678"


def test_no_false_positive_on_course_names():
    # 학과·과목명은 재식별 quasi지만 마스킹 대상이 아님. 그대로 통과.
    assert redact_text("컴퓨터공학과 자료구조 3학점") == "컴퓨터공학과 자료구조 3학점"


def test_mask_data_nested():
    payload = {
        "messages": [
            {"role": "user", "content": "202112345 홍길동입니다"},
            {"role": "assistant", "content": "메일 ldw2003@pusan.ac.kr 확인했어요"},
        ],
        "career_goal": "010-1234-5678로 상담 부탁드려요",
        "credits": 21,
    }
    out = mask_data(payload)
    assert out["messages"][0]["content"] == "<STUDENT_ID> 홍길동입니다"
    assert out["messages"][1]["content"] == "메일 <EMAIL> 확인했어요"
    assert out["career_goal"] == "<PHONE>로 상담 부탁드려요"
    assert out["credits"] == 21  # 정수는 원본 유지


def test_mask_data_handles_none_and_bool():
    assert mask_data(None) is None
    assert mask_data(True) is True
    assert mask_data(3.14) == 3.14
