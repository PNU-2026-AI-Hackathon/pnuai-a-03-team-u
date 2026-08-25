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

    def test_evaluation_method_drops_accessibility_boilerplate_and_label(self):
        """이 샘플의 평가방법 셀에는 실제 배점 뒤에 장애학생 안내문(원본 텍스트가
        "...있습니\\n다."로 두 줄에 걸쳐 있음)이 붙어 있다 — 교수가 쓴 내용이
        아니므로 남으면 안 된다."""
        self.assertNotIn("장애학생", self.parsed.evaluation_method)
        self.assertNotIn("평가방법", self.parsed.evaluation_method)

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

    def test_overview_drops_accessibility_boilerplate_and_label(self):
        """"강의개요" 레이블 뒤에 장애학생 안내문이 붙어 있다 — 둘 다 교수가 쓴
        실제 강의개요가 아니므로 남으면 안 된다."""
        self.assertNotIn("장애학생", self.parsed.course_overview)
        self.assertNotIn("강의개요", self.parsed.course_overview)

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



class EmptyCellAccessibilityBoilerplateTest(unittest.TestCase):
    """실제 One-Stop PDF(인공지능이해 FM2003112분반001, 2026-2학기, 2026-08-25
    다운로드)를 그대로 옮긴 것 — 교수가 연락처/평가방법/교수목표/강의개요를 전부
    비워둔 실제 사례. 예전엔 이 셀들이 비어 있으면 그 자리를 차지하는 장애학생
    안내문(One-Stop 템플릿이 자동으로 넣는 문구, 교수가 쓴 게 아니다)이나
    레이블 단어 자체가 실제 내용인 것처럼 그대로 저장됐다."""

    def setUp(self):
        self.parsed = parse_syllabus_text('                 2026학년도 2학기 교수계획표\n교과목명       인공지능이해      교과목번호        FM2003112     분반            001\n\n개설학과      미래모빌리티전공      개설학년          3학년       학점-이론-실습   2.0 - 2.0 - 0.0\n\n강의시간\n및 강의실\n                         연구실\n                                                 상담시간\n                      (상담가능장소)\n담당교수\n                        연락처                       이메일\n\n         ㆍ대면\n수업방식\n         ㆍ강의식\n\n\n\n평가방법\n         * 장애학생의 경우 시험기간의 연장이 가능하며, 대필이나 컴퓨터를 활용하여 시험에 응시할 수 있습니\n         다.\n선수과목 및\n  지식\n\n교수목표\n\n\n\n         * 장애학생의 경우 장애학습지원센터와 강의 및 과제에 대한 사전 협의가 가능합니다.\n강의개요\n\n\n\n                               교재 및 참고문헌\n\n\n직접입력     "밑바닥부터 시작하는 딥러닝"-사이토 고키 지음 한빛미디어 2017')

    def test_empty_objectives_and_overview_become_none_not_boilerplate(self):
        self.assertIsNone(self.parsed.course_objectives)
        self.assertIsNone(self.parsed.course_overview)

    def test_empty_evaluation_method_becomes_none_not_boilerplate(self):
        self.assertIsNone(self.parsed.evaluation_method)

    def test_teaching_mode_still_extracted_when_contact_info_is_blank(self):
        """담당교수가 연락처/이메일을 아예 안 채운 경우, 예전엔 그 값 매치 실패로
        수업방식 추출 자체가 통째로 None이 됐다(2026-08-25 실측) — 실제로 있는
        "ㆍ대면"/"ㆍ강의식" 내용은 살아있어야 한다."""
        self.assertIn("ㆍ대면", self.parsed.teaching_mode)
        self.assertIn("ㆍ강의식", self.parsed.teaching_mode)
        self.assertNotIn("수업방식", self.parsed.teaching_mode)

    def test_contact_absent_is_none_not_crash(self):
        self.assertIsNone(self.parsed.phone)
        self.assertIsNone(self.parsed.email)


class LabelAndBoilerplateSharingContentLineTest(unittest.TestCase):
    """실제 One-Stop PDF(유기화학 AB2002371분반140, 2026-2학기, 2026-08-25
    다운로드)를 그대로 옮긴 것. 두 가지 실제 함정을 같이 담고 있다:
    (1) 이메일이 길어서 "담당교수"/"연락처" 표 셀 안에서 줄이 꺾여, "이메일"
    레이블이 있는 줄 자체엔 값이 없고 가운데 줄에 앞부분, 그다음 줄에 한 글자
    (`r`)만 잔재로 남는다 — 이 잔재를 수업방식 내용 시작으로 착각하면 안 된다.
    (2) 장애학생 안내문(영문판 포함)과 레이블 단어가 교수가 실제로 쓴 내용과
    같은 물리적 줄에 바로 이어 붙는다(예: "Attitude 10%, Attendance 10%, Exam
    80% , * Students with disabilities can request...", "강의개요     After
    learning...") — 실제 내용까지 통째로 버리면 안 되고, 레이블/안내문만 벗겨야
    한다."""

    def setUp(self):
        self.parsed = parse_syllabus_text('                          2026학년도 2학기 교수계획표\n 교과목명            유기화학                   교과목번호            AB2002371               분반                   140\n\n 개설학과      첨단바이오공학전공                    개설학년               2학년             학점-이론-실습              3.0 - 3.0 - 0.0\n\n강의시간\n                                        월 10:30(75) 양산Y17-101, 수 10:30(75) 양산Y17-101\n및 강의실\n                                      연구실\n                                                                              상담시간\n                                   (상담가능장소)\n 담당교수             정상화\n                                                                                           sanghwa.jeong@pusan.ac.k\n                                         연락처                8539               이메일\n                                                                                                       r\n\n          ㆍ대면\n 수업방식\n          ㆍ강의식\n\n\n          Attitude 10%, Attendance 10%, Exam 80% , * Students with disabilities can request an extension of the\n 평가방법     exam hour, and they can take exams by getting writing assistance or by using a computer.\n          * 장애학생의 경우 시험기간의 연장이 가능하며, 대필이나 컴퓨터를 활용하여 시험에 응시할 수 있습니\n          다.\n선수과목 및\n          General Chemistry (I), (II)\n  지식\n          This lecture will cover the basic level of organic chemistry, and provide the important chemical reactio\n          ns for biomedical engineering applications.\n 교수목표     After learning organic chemistry, students may understand the fundamental properties of organic molecu\n          les such as solvent, drug, polymer, and biomaterials.\n\n          - Chemical bonding and resonance structures in organic molecules\n          - How the acid/base and nucleophile/electrophile is related with chemical reactivity\n          - Important conjugation chemistries in biomedical engineering\n          - Regiochemistry and stereochemistry of organic molecules\n 강의개요\n          * 장애학생의 경우 장애학습지원센터와 강의 및 과제에 대한 사전 협의가 가능합니다.\n\n\n\n\n                                           교과목과 핵심역량과의 관계\n\n               지구시민                     소통협력              지식탐구                  혁신도전                  창의융합\n 부산대학교\n5대 핵심역량\n                                                             O\n\n                                             교과목에 따른 핵심역량\n\n                       학과 핵심역량                                                         교육방법\n\n  01      지식탐구                                                       수업\n\n                                                교재 및 참고문헌\n\n\n 직접입력     (주교재)Atkins et al., Organic Chemistry:A brief course, 3rd Edition, McGraw-Hill')

    def test_wrapped_email_fragment_does_not_become_teaching_mode(self):
        self.assertIn("ㆍ대면", self.parsed.teaching_mode)
        self.assertIn("ㆍ강의식", self.parsed.teaching_mode)
        self.assertNotEqual("r", self.parsed.teaching_mode)

    def test_evaluation_method_keeps_real_content_before_english_boilerplate(self):
        self.assertIn("Attitude 10%, Attendance 10%, Exam 80%", self.parsed.evaluation_method)
        self.assertNotIn("Students with disabilities", self.parsed.evaluation_method)
        self.assertNotIn("장애학생", self.parsed.evaluation_method)
        self.assertNotIn("평가방법", self.parsed.evaluation_method)

    def test_overview_keeps_real_content_and_drops_leading_label_and_boilerplate(self):
        self.assertIn("Chemical bonding and resonance structures", self.parsed.course_overview)
        self.assertNotIn("강의개요", self.parsed.course_overview)
        self.assertNotIn("장애학생", self.parsed.course_overview)

    def test_textbooks_still_reached_after_all_the_above(self):
        self.assertIn("Atkins", self.parsed.textbooks)


class LabelWhitespaceInsensitiveTest(unittest.TestCase):
    """"주별 강의계획"(공백 있음)과 "주별강의계획"(공백 없음) 둘 다 실제 PDF에서
    나온다(2026-08-25 실측, 마케팅조사론 DB3000786분반091은 공백 없는 쪽) —
    공백 하나 다르다고 라벨을 못 찾으면 그 뒤 섹션 경계가 통째로 무너져서
    주별 강의계획 표 전체가 textbooks에 섞여 들어갔었다."""

    def test_find_label_line_ignores_internal_whitespace_variance(self):
        from app.ingestion.parsers.onestop_syllabus import _find_label_line

        lines_with_space = ["아무 내용", "주별 강의계획", "표 내용"]
        lines_without_space = ["아무 내용", "주별강의계획", "표 내용"]
        self.assertEqual(1, _find_label_line(lines_with_space, "주별 강의계획"))
        self.assertEqual(1, _find_label_line(lines_without_space, "주별 강의계획"))
        self.assertEqual(1, _find_label_line(lines_with_space, "주별강의계획"))


if __name__ == "__main__":
    unittest.main()
