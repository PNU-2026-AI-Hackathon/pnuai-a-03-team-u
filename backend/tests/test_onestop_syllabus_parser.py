"""One-Stop 교수계획표(강의계획서) PDF 텍스트 파서 테스트.

고정 텍스트는 실제 One-Stop 교수계획표 PDF(자료구조 VF3500075분반101,
2026-2학기, 2026-08-24 실제 다운로드해서 `pdftotext -layout`으로 뽑은 것 —
`app.ingestion.crawlers.onestop_syllabus`로 재현 가능)를 그대로 옮긴 것이다.
표 셀 레이블이 세로 중앙 정렬이라 레이블 줄 앞뒤로 내용이 걸쳐 있는 실제 함정을
그대로 담고 있다(파서 모듈 docstring 참고) — 지어낸 텍스트가 아니다.
"""

import unittest

from app.ingestion.parsers.onestop_syllabus import parse_syllabus_text

_SAMPLE_TEXT = """                    2026학년도 2학기 교수계획표
교과목명         자료구조         교과목번호          VF3500075            분반                101

         디자인앤테크놀로지전
개설학과                       개설학년            2학년              학점-이론-실습       3.0 - 3.0 - 0.0
              공
강의시간
                                    화 10:00-13:00 704-406
및 강의실
                            연구실
                                                             상담시간
                         (상담가능장소)
담당교수          이다영
                            연락처         051-510-1436          이메일      schematique@pusan.ac.kr

         ㆍ대면
수업방식
         ㆍ강의식, 실험·실습·실기


         과제물 30%, 중간고사 30%, 기말고사 35%, 출석 5%, 시험은 필기 + 프로그래밍 동시에 실시합니다.
평가방법
         * 장애학생의 경우 시험기간의 연장이 가능하며, 대필이나 컴퓨터를 활용하여 시험에 응시할 수 있습니
         다.
선수과목 및
         파이썬, C언어, java 중 최소 1개 언어를 배운 뒤 수강하시기 바랍니다.
  지식
         1. 현장에서 요구되는 문제를 효율적으로 해결하기 위한 기초적인 자료구조를 익힌다.
         2. 주 내용은 변수, 배열(array), 리스트, 스택과 큐, 그래프 구조, 사전(Dict)를 포함한다.
교수목표     3. 좋은 자료구조가 보장하는 프로그램의 성능 차이를 이해한다.
         4. 실습용으로 사용되는 Java 언어의 구조와 Java에서 다양한 package를 살펴본다.
         5. 시의성 있는 문제를 통하여 잘 설계된 자료구조의 유용성을 익힌다.
         강의는 해당 주차에 배울 자료구조 설명 + 과제 리뷰 + 프로그래밍 실습으로 구성됩니다.
         과제는 배운 내용을 응용해서 풀 수 있는 문제로 구성됩니다.
         실제 자료구조를 구현하고 응용하는 과목이므로, Java 또는 프로그래밍 언어 과목을 1개 이상 수강하고
         들으시길 권장합니다.
강의개요
         * 장애학생의 경우 장애학습지원센터와 강의 및 과제에 대한 사전 협의가 가능합니다.




                                  교재 및 참고문헌

         1    부교재    문병로,『쉽게 배우는 자료구조 with 자바』-한빛아카데미(2022)
검색입력
         2    부교재    양성봉,『(자바와 함께하는)자료구조의 이해』-생능출판(생능출판사)(2023)

         (주교재) 강의안은 매주 pdf 형태로 plato에 업로드 할 예정입니다.
직접입력
                               주별 강의계획

  주차                강의 및 실험 실기 내용               과제 및 기타 참고사항

          [표절, 시험 부정행위 예방교육 및 실험·실습 안전교육
 제1주                                       프로그래밍 과제
          실시] 자료구조 개요
          자바 복습 1
 제2주                                       프로그래밍 과제
          - 자바 기초 문법, 파일 입출력
          자바 복습 2
 제3주                                       프로그래밍 과제
          - 클래스

 제4주      자료구조 성능 평가, 복잡도                  프로그래밍 과제

  제15주
          그래프 알고리즘                         프로그래밍 과제
(지정보강주)

 제16주     기말고사
"""


class SyllabusParserTest(unittest.TestCase):
    def setUp(self):
        self.parsed = parse_syllabus_text(_SAMPLE_TEXT)

    def test_contact(self):
        self.assertEqual("051-510-1436", self.parsed.phone)
        self.assertEqual("schematique@pusan.ac.kr", self.parsed.email)

    def test_teaching_mode_content_wraps_the_centered_label(self):
        """"수업방식" 레이블이 "ㆍ대면"과 "ㆍ강의식..." 사이에 끼어 있어도 둘 다 잡아야 한다."""
        self.assertIn("ㆍ대면", self.parsed.teaching_mode)
        self.assertIn("ㆍ강의식, 실험·실습·실기", self.parsed.teaching_mode)

    def test_evaluation_method_captures_percentages_before_the_label(self):
        """평가방법 실제 배점("과제물 30%...")이 "평가방법" 레이블보다 앞줄에 있다 —
        레이블 위치만 보면 이걸 놓친다(2026-08-24 첫 구현에서 실제로 놓쳤던 회귀)."""
        self.assertIn("과제물 30%", self.parsed.evaluation_method)
        self.assertIn("중간고사 30%", self.parsed.evaluation_method)

    def test_prerequisites_bracketed_by_two_line_label(self):
        self.assertEqual(
            "파이썬, C언어, java 중 최소 1개 언어를 배운 뒤 수강하시기 바랍니다.",
            self.parsed.prerequisites_text,
        )

    def test_objectives_stop_at_last_numbered_item(self):
        self.assertIn("5. 시의성 있는 문제를", self.parsed.course_objectives)
        self.assertNotIn("강의는 해당 주차에", self.parsed.course_objectives)

    def test_overview_is_the_unnumbered_tail(self):
        self.assertIn("강의는 해당 주차에", self.parsed.course_overview)
        self.assertIn("들으시길 권장합니다", self.parsed.course_overview)
        self.assertNotIn("5. 시의성 있는 문제를", self.parsed.course_overview)

    def test_textbooks(self):
        self.assertIn("문병로", self.parsed.textbooks)
        self.assertIn("양성봉", self.parsed.textbooks)

    def test_core_competencies_absent_section_is_none(self):
        """이 샘플엔 "교과목과 핵심역량과의 관계" 섹션 자체가 없다(교수 재량으로
        빠짐) — 지어내지 않고 None이어야 한다."""
        self.assertIsNone(self.parsed.core_competencies)

    def test_weekly_plan_parses_week_markers(self):
        weeks = {w["week"]: w["content"] for w in self.parsed.weekly_plan}
        self.assertIn("제1주", weeks)
        self.assertIn("자료구조 개요", weeks["제1주"])
        self.assertIn("제4주", weeks)
        self.assertIn("자료구조 성능 평가", weeks["제4주"])

    def test_weekly_plan_keeps_content_that_precedes_its_own_week_marker(self):
        """"[표절, 시험 부정행위 예방교육..." 줄이 "제1주" 레이블 줄보다 앞에 있다
        (같은 세로중앙정렬 함정, 독립 리뷰 2026-08-24 지적) — 잃으면 안 된다."""
        weeks = {w["week"]: w["content"] for w in self.parsed.weekly_plan}
        self.assertIn("표절", weeks["제1주"])

    def test_weekly_plan_does_not_leak_the_column_header_row(self):
        """"주차 / 강의 및 실험 실기 내용 / 과제 및 기타 참고사항" 표 헤더는 내용이
        아니다 — 어느 주차에도 안 붙어야 한다."""
        for week in self.parsed.weekly_plan:
            self.assertNotIn("과제 및 기타 참고사항", week["content"])

    def test_weekly_plan_strips_the_지정보강주_marker(self):
        weeks = {w["week"]: w["content"] for w in self.parsed.weekly_plan}
        self.assertIn("제15주", weeks)
        self.assertNotIn("지정보강주", weeks["제15주"])

    def test_raw_text_preserved_verbatim(self):
        """구조화 파싱이 뭘 놓치든, 원문 전체는 그대로 남아야 한다(모델 docstring 참고)."""
        self.assertEqual(_SAMPLE_TEXT, self.parsed.raw_text)


if __name__ == "__main__":
    unittest.main()
