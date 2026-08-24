import { ArrowLeft } from "lucide-react";
import { Link } from "react-router-dom";
import { BrandMark } from "../components/layout/BrandMark";

/**
 * 개인정보처리방침 · LLM 처리위탁 고지.
 *
 * 회원가입 동의 체크박스에서 링크로 연다(공개 라우트, 로그인 여부와 무관하게 접근 가능).
 * 내용은 실제 코드 감사 결과(docs/backend/security-privacy-plan.md,
 * docs/backend/features/llm-privacy-audit.md)를 근거로 작성했다 — 아직 구현되지 않은
 * 것(자동 파기 스케줄 등)은 "구현 예정"이라고 정직하게 적는다. 실제로 안 하는 걸 하는
 * 것처럼 적으면 이 문서 자체가 개인정보보호법 위반의 근거가 된다.
 */
export function PrivacyPolicyPage() {
  return (
    <main className="auth-screen route-view">
      <section className="auth-shell privacy-shell">
        <Link className="auth-logo" to="/auth" aria-label="로그인으로">
          <BrandMark id="plan-u-face-privacy" />
          <span>
            Plan <strong>U</strong>
          </span>
        </Link>

        <article className="auth-panel privacy-doc">
          <div className="auth-title">
            <h1>개인정보처리방침 · LLM 처리위탁 고지</h1>
            <p>시행일 2026-08-24. Plan U는 부산대학교 재학생의 학사정보를 다루는 학생 프로젝트입니다.</p>
          </div>

          <h2>1. 수집하는 개인정보 항목</h2>
          <table className="privacy-table">
            <thead>
              <tr>
                <th>구분</th>
                <th>항목</th>
                <th>수집 시점</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>계정 식별자</td>
                <td>이름, 학번, 부산대 웹메일, 비밀번호(해시 저장)</td>
                <td>회원가입</td>
              </tr>
              <tr>
                <td>학사 정보</td>
                <td>학과·전공·학년, 지도교수명, 이수내역·성적, 졸업요건 진행 현황</td>
                <td>회원가입, 학생지원시스템 동기화</td>
              </tr>
              <tr>
                <td>학업·진로 정보</td>
                <td>자격증·어학 성적, 비교과 활동, 진로 목표(자유 입력)</td>
                <td>내 정보 화면에서 직접 입력, 학생지원시스템 동기화</td>
              </tr>
              <tr>
                <td>서비스 이용 기록</td>
                <td>로드맵·시간표 계획, AI 상담 대화 원문, 마지막 로그인 시각</td>
                <td>서비스 이용 중 자동 생성</td>
              </tr>
            </tbody>
          </table>
          <p className="privacy-note">
            학생지원시스템(One-Stop) 로그인 아이디·비밀번호는 학사정보를 가져오는 요청을 처리하는
            동안만 사용하고 서버에 저장하지 않습니다.
          </p>

          <h2>2. 수집·이용 목적</h2>
          <ul>
            <li>졸업요건 자동 분석 — 이수내역과 학과별 규칙을 대조해 충족·미충족을 판정합니다(규칙 기반 엔진만 판정하며, AI는 판정에 관여하지 않습니다).</li>
            <li>AI 학업 로드맵 추천 — 남은 학기에 무엇을 들어야 하는지 제안합니다. 제안은 사용자가 직접 승인한 것만 반영됩니다.</li>
            <li>AI 시간표 추천 — 다음 학기 개설 강좌 중 시간 충돌 없는 조합을 제안합니다. 마찬가지로 사용자 승인이 있어야 반영됩니다.</li>
          </ul>

          <h2>3. 처리위탁 — 외부로 나가는 정보</h2>
          <p>
            서비스 제공을 위해 아래 두 곳에 정보 처리를 위탁합니다. 회원 탈퇴·문의 대응 등 다른
            목적으로 제3자에게 개인정보를 판매하거나 제공하지 않습니다.
          </p>
          <table className="privacy-table">
            <thead>
              <tr>
                <th>수탁업체</th>
                <th>위탁 업무</th>
                <th>전송하는 항목 / 보내지 않는 항목</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>OpenAI</td>
                <td>AI 로드맵·시간표 상담(LLM 응답 생성), 교육과정 검색용 임베딩 생성</td>
                <td>
                  전송: 과목명·이수구분, 진로 목표, 로드맵/시간표 계획, 채팅 대화 원문<br />
                  미전송: 이름·학번·이메일·성적 등급
                </td>
              </tr>
              <tr>
                <td>Langfuse(자체 호스팅)</td>
                <td>AI 응답 품질 관측·개선(트레이싱)</td>
                <td>
                  전송: 위와 같은 대화 내용이 이메일·휴대폰·유선번호·학번 패턴 마스킹을 거친 뒤 전송되고,
                  사용자 식별자는 원문 대신 해시값으로 남습니다.<br />
                  당사가 직접 운영하는 서버로 전송되며, 제3자 클라우드로 나가지 않습니다.
                </td>
              </tr>
            </tbody>
          </table>

          <h2>4. 보유 기간 및 파기</h2>
          <ul>
            <li>회원 탈퇴 시 계정과 학사 데이터를 즉시 삭제합니다(구현 완료).</li>
            <li>
              장기간(기본 24개월) 로그인하지 않은 계정은 보존기간 정책에 따라 파기합니다. 파기
              도구는 구현되어 있으나, 자동 실행은 백업·복구 절차 검증을 마친 뒤 활성화할
              예정입니다 — 이 문서를 보는 시점에 아직 자동 실행되지 않을 수 있습니다.
            </li>
            <li>Langfuse에 남는 트레이싱 기록은 계정 삭제와 별도 절차로 파기합니다.</li>
          </ul>

          <h2>5. 이용자의 권리</h2>
          <ul>
            <li>내 정보 화면에서 언제든 본인의 학사 정보·프로필을 직접 열람·수정할 수 있습니다.</li>
            <li>회원 탈퇴를 요청하면 위 3항의 위탁 처리를 포함해 보유 중인 개인정보가 즉시 삭제됩니다.</li>
          </ul>

          <h2>6. 문의</h2>
          <p>
            이 방침이나 개인정보 처리에 대해 궁금한 점은 프로젝트 저장소 이슈로 남겨주세요:{" "}
            <a
              href="https://github.com/PNU-2026-AI-Hackathon/pnuai-a-03-team-u/issues"
              target="_blank"
              rel="noopener noreferrer"
            >
              github.com/PNU-2026-AI-Hackathon/pnuai-a-03-team-u
            </a>
          </p>
        </article>

        <Link className="reset-back" to="/auth">
          <ArrowLeft size={15} aria-hidden="true" />
          로그인으로 돌아가기
        </Link>
      </section>
    </main>
  );
}
