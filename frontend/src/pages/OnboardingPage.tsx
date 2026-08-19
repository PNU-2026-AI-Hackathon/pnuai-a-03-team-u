import { useState } from "react";
import type { FormEvent } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { ArrowLeft, Check, ClipboardCheck } from "lucide-react";
import { BrandMark } from "../components/layout/BrandMark";
import { SignupStepper } from "../components/auth/SignupStepper";
import { summarizePortalSync, syncFromPortal } from "../api/portal";
import { getApiErrorMessage } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { clearSignupFlow, hasActiveSignupFlow } from "../auth/signupFlow";

type Summary = ReturnType<typeof summarizePortalSync>;

/** 회원가입 STEP 2·3. 로그인된 뒤에만 들어올 수 있다. */
export function OnboardingPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { user } = useAuth();
  const step: 2 | 3 = location.state?.signupStep === 3 ? 3 : 2;
  const [portalId, setPortalId] = useState(user?.student_id ?? "");
  const [portalPassword, setPortalPassword] = useState("");
  const [summary, setSummary] = useState<Summary | null>(null);
  const [isSyncing, setIsSyncing] = useState(false);
  const [error, setError] = useState("");

  const displayName = user?.name ?? "회원";

  function handleBack() {
    if (step === 3) {
      navigate(-1);
      return;
    }
    if (hasActiveSignupFlow()) {
      navigate("/auth");
      return;
    }
    navigate("/", { replace: true });
  }

  function goToCompletion() {
    navigate("/onboarding", { state: { signupStep: 3 } });
  }

  function finishSignup(path: string) {
    clearSignupFlow();
    navigate(path, { replace: true });
  }

  async function handleSync(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setIsSyncing(true);
    try {
      setSummary(summarizePortalSync(await syncFromPortal(portalId, portalPassword)));
    } catch (caught) {
      setError(getApiErrorMessage(caught, "학사정보를 불러오지 못했습니다. 아이디와 비밀번호를 확인해 주세요."));
    } finally {
      setIsSyncing(false);
    }
  }

  const previewRows = summary
    ? [
        { title: [summary.name, summary.studentId && `(${summary.studentId})`].filter(Boolean).join(" "), sub: "이름, 학번" },
        { title: summary.affiliation, sub: "소속" },
        { title: `${summary.totalCredits}학점 · ${summary.courseCount}과목`, sub: "이수 학점, 성적 포함" },
        { title: summary.academicStatus, sub: "학적 상태" },
      ].filter((row) => row.title)
    : [];

  const doneRows = [
    {
      title: summary ? `이수 내역 ${summary.courseCount}과목 · ${summary.totalCredits}학점 등록` : "계정 생성 완료",
      sub: summary ? "학생지원시스템 동기화" : "학사정보는 내 정보에서 추가할 수 있어요",
    },
    summary
      ? {
          title: summary.graduationTableCount > 0
            ? `졸업요건 분석 완료 · 기준표 ${summary.graduationTableCount}개`
            : "졸업요건 분석 완료",
          sub: summary.affiliation ?? "소속 학과 기준",
        }
      : { title: "졸업요건 분석 준비", sub: "학사정보 등록 후 분석할 수 있어요" },
    {
      title: "성장 로드맵 초안 생성",
      sub: user?.academic_year ? `${user.academic_year}학년 1학기 ~ 4학년 2학기` : "학기별 이수 계획",
    },
  ];

  return (
    <main className="auth-screen route-view">
      <section className={`auth-shell is-signup ${step === 2 ? "is-wide" : "is-complete"}`}>
        <div className="onboarding-brand-row">
          <button
            className="onboarding-back"
            type="button"
            aria-label={step === 3 ? "학사정보 단계로 돌아가기" : "이전 단계로 돌아가기"}
            title={step === 3 ? "학사정보 단계로 돌아가기" : "이전 단계로 돌아가기"}
            onClick={handleBack}
          >
            <ArrowLeft size={20} aria-hidden="true" />
          </button>
          <span className="auth-logo" aria-hidden="true">
            <BrandMark id="plan-u-face-onboarding" />
            <span>
              Plan <strong>U</strong>
            </span>
          </span>
          <span aria-hidden="true" />
        </div>

        <SignupStepper current={step} />

        {step === 2 ? (
          <div className="onboarding-columns onboarding-step-enter" key="step-2">
            <form className="auth-panel" onSubmit={handleSync}>
              <div className="auth-title">
                <p className="eyebrow">STEP 2 · AUTO IMPORT</p>
                <h1>학생지원시스템에서 학사정보 불러오기</h1>
                <p>
                  이수 과목 · 성적 · 학적 정보를 자동으로 등록합니다.
                  <br />
                  학생지원시스템 계정 정보는 저장되지 않습니다.
                </p>
              </div>

              <label className="auth-field">
                <span>학생지원시스템 아이디</span>
                <input
                  type="text"
                  inputMode="numeric"
                  placeholder="학번을 입력하세요"
                  value={portalId}
                  onChange={(event) => setPortalId(event.target.value)}
                  required
                />
              </label>
              <label className="auth-field">
                <span>학생지원시스템 비밀번호</span>
                <input
                  type="password"
                  placeholder="비밀번호를 입력하세요"
                  value={portalPassword}
                  onChange={(event) => setPortalPassword(event.target.value)}
                  required
                />
              </label>

              <div className={`auth-message${error ? " error" : ""}`} aria-live="assertive">
                {error}
              </div>

              <div className="onboarding-actions">
                <button className="auth-submit" type="submit" disabled={isSyncing}>
                  {isSyncing ? "불러오는 중..." : "학사정보 불러오기"}
                </button>
                <button className="auth-submit ghost" type="button" onClick={goToCompletion}>
                  직접 입력할게요
                </button>
              </div>

              <p className="onboarding-note">✓ 개인정보 수집 · 이용 동의 · 성적표 원본은 저장하지 않습니다</p>
            </form>

            <div className="auth-panel onboarding-preview">
              <header>
                <h2><ClipboardCheck size={20} aria-hidden="true" /> 불러온 정보 미리보기</h2>
                {summary ? (
                  <span className={`onboarding-badge${summary.myPusanFailed ? " is-partial" : ""}`}>
                    {summary.myPusanFailed ? "일부만 완료" : "동기화 완료"}
                  </span>
                ) : null}
              </header>

              {summary ? (
                <>
                  <ul>
                    {previewRows.map((row) => (
                      <li key={row.sub}>
                        <span className="onboarding-check" aria-hidden="true">
                          <Check size={14} />
                        </span>
                        <span>
                          <strong>{row.title}</strong>
                          <span>{row.sub}</span>
                        </span>
                      </li>
                    ))}
                  </ul>
                  {summary.myPusanFailed ? (
                    <p className="onboarding-warning" role="status">
                      {summary.myPusanFailedMessage}
                    </p>
                  ) : null}
                  <button className="auth-submit" type="button" onClick={goToCompletion}>
                    확인하고 시작하기
                  </button>
                  <p className="onboarding-note">잘못된 항목은 가입 후 내 정보에서 수정할 수 있어요</p>
                </>
              ) : (
                <p className="onboarding-empty">
                  왼쪽에서 학사정보를 불러오면 여기에 등록될 내용을 먼저 확인할 수 있습니다.
                </p>
              )}
            </div>
          </div>
        ) : (
          <div className="auth-panel onboarding-done onboarding-step-enter" key="step-3">
            <span className="onboarding-done-mark" aria-hidden="true">
              <Check size={20} />
            </span>
            <div className="onboarding-done-title">
              <h1>가입이 완료되었습니다!</h1>
              <p>{displayName} 님의 학사 데이터를 기반으로 개인 로드맵을 준비했어요.</p>
            </div>

            <ul>
              {doneRows.map((row) => (
                <li key={row.title}>
                  <span className="onboarding-check" aria-hidden="true">
                    <Check size={14} />
                  </span>
                  <span>
                    <strong>{row.title}</strong>
                    <span>{row.sub}</span>
                  </span>
                </li>
              ))}
            </ul>

            <div className="onboarding-done-footer">
              <div className="onboarding-actions">
                <button className="auth-submit" type="button" onClick={() => finishSignup("/")}>
                  홈으로 시작하기
                </button>
                <button
                  className="auth-submit ghost"
                  type="button"
                  onClick={() => finishSignup("/roadmap")}
                >
                  성장 로드맵 보기
                </button>
              </div>

              <p className="onboarding-note">비교과 · 자격증 · 어학 정보는 내 정보에서 직접 추가할 수 있어요</p>
            </div>
          </div>
        )}
      </section>
    </main>
  );
}
