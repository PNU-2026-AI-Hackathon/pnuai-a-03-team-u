import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { BrandMark } from "../components/layout/BrandMark";
import { SignupStepper } from "../components/auth/SignupStepper";
import { useAuth } from "../auth/AuthContext";
import type { AcademicProgramInput } from "../api/auth";
import { getApiErrorMessage } from "../api/client";

type AuthMode = "login" | "signup";
type MessageKind = "error" | "success";

/** 로그인 화면 하단 통계. 시안에 있는 값이라 그대로 둔다. */
const loginHighlights = [
  { value: "112 / 130", label: "졸업 요건 학점" },
  { value: "6건 관리", label: "비교과 활동" },
  { value: "3학년 1학기", label: "현재 학기" },
];

export function AuthPage() {
  const navigate = useNavigate();
  const { loginWithStudentId, signupWithEmail } = useAuth();
  const [mode, setMode] = useState<AuthMode>("login");
  const [message, setMessage] = useState("");
  const [loginMessage, setLoginMessage] = useState("");
  const [loginMessageKind, setLoginMessageKind] = useState<MessageKind>("error");
  const [isLoginSubmitting, setIsLoginSubmitting] = useState(false);
  const [isSignupSubmitting, setIsSignupSubmitting] = useState(false);
  const [loginStudentId, setLoginStudentId] = useState("");
  const [loginPassword, setLoginPassword] = useState("");
  const [rememberLogin, setRememberLogin] = useState(false);
  const [signupPassword, setSignupPassword] = useState("");
  const [signupEmail, setSignupEmail] = useState("");
  const [signupName, setSignupName] = useState("");
  const [studentId, setStudentId] = useState("");
  const [department, setDepartment] = useState("");
  const [careerGoal, setCareerGoal] = useState("");
  const [minorMajor, setMinorMajor] = useState("");
  const [dualMajor, setDualMajor] = useState("");

  async function handleLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoginMessage("");
    setLoginMessageKind("error");
    setIsLoginSubmitting(true);
    try {
      await loginWithStudentId(loginStudentId, loginPassword, rememberLogin);
      navigate("/", { replace: true });
    } catch (error) {
      setLoginMessage(getApiErrorMessage(error, "로그인에 실패했습니다. 입력한 정보를 확인해 주세요."));
    } finally {
      setIsLoginSubmitting(false);
    }
  }

  /**
   * STEP 1. 계정을 만들고 바로 로그인시킨 뒤 STEP 2로 넘긴다. 학사정보 불러오기가
   * 인증이 필요한 엔드포인트라 STEP 2·3은 /onboarding에서 이어진다.
   */
  async function handleSignup(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage("");

    if (signupPassword.length < 8) {
      setMessage("비밀번호는 8자 이상이어야 합니다.");
      return;
    }
    if (!signupName.trim()) {
      setMessage("이름을 입력해주세요.");
      return;
    }

    const academicPrograms: AcademicProgramInput[] = [];
    if (department.trim()) {
      academicPrograms.push({ department: department.trim(), program_type: "primary" });
    }
    if (minorMajor.trim()) {
      academicPrograms.push({ department: minorMajor.trim(), program_type: "minor" });
    }
    if (dualMajor.trim()) {
      academicPrograms.push({ department: dualMajor.trim(), program_type: "dual" });
    }

    setIsSignupSubmitting(true);
    try {
      await signupWithEmail({
        email: signupEmail,
        password: signupPassword,
        name: signupName,
        student_id: studentId,
        school: "부산대학교",
        department: department || undefined,
        career_goal: careerGoal || undefined,
        academic_programs: academicPrograms,
      });
      await loginWithStudentId(studentId, signupPassword, false);
      navigate("/onboarding", { replace: true });
    } catch (error) {
      setMessage(getApiErrorMessage(error, "회원가입에 실패했습니다. 입력한 정보를 확인해 주세요."));
    } finally {
      setIsSignupSubmitting(false);
    }
  }

  return (
    <main className="auth-screen">
      <section className={`auth-shell${mode === "signup" ? " is-signup" : ""}`}>
        <Link className="auth-logo" to="/" aria-label="Plan U 홈">
          <BrandMark id="plan-u-face-auth" />
          <span>
            Plan <strong>U</strong>
          </span>
        </Link>

        {mode === "signup" ? <SignupStepper current={1} /> : null}

        <div className="auth-panel">
          <div className="auth-tabs" role="tablist" aria-label="인증 방식 선택">
            <button
              className={mode === "login" ? "selected" : ""}
              type="button"
              role="tab"
              aria-selected={mode === "login"}
              onClick={() => setMode("login")}
            >
              로그인
            </button>
            <button
              className={mode === "signup" ? "selected" : ""}
              type="button"
              role="tab"
              aria-selected={mode === "signup"}
              onClick={() => setMode("signup")}
            >
              회원가입
            </button>
          </div>

          {mode === "login" ? (
            <form className="auth-form" onSubmit={handleLogin}>
              <div className="auth-title">
                <p className="eyebrow">Welcome Back</p>
                <h1>로그인</h1>
                <p>Plan U 계정으로 내 정보를 이어서 확인합니다.</p>
              </div>

              <label className="auth-field">
                <span>학번 입력</span>
                <input
                  type="text"
                  inputMode="numeric"
                  autoComplete="username"
                  placeholder="학번을 입력하세요"
                  value={loginStudentId}
                  onChange={(event) => setLoginStudentId(event.target.value)}
                  required
                />
              </label>
              <label className="auth-field">
                <span>비밀번호 입력</span>
                <input
                  type="password"
                  autoComplete="current-password"
                  placeholder="비밀번호를 입력하세요"
                  value={loginPassword}
                  onChange={(event) => setLoginPassword(event.target.value)}
                  required
                />
              </label>

              <div
                className={`auth-message${loginMessage ? ` ${loginMessageKind}` : ""}`}
                aria-live={loginMessageKind === "error" ? "assertive" : "polite"}
              >
                {loginMessage}
              </div>

              <div className="auth-options">
                <label>
                  <input
                    type="checkbox"
                    checked={rememberLogin}
                    onChange={(event) => setRememberLogin(event.target.checked)}
                  />
                  로그인 유지
                </label>
                <Link to="/forgot-password">비밀번호 찾기</Link>
              </div>

              <button className="auth-submit" type="submit" disabled={isLoginSubmitting}>
                {isLoginSubmitting ? "로그인 중..." : "로그인"}
              </button>

              <p className="auth-switch">
                아직 계정이 없나요?{" "}
                <button type="button" onClick={() => setMode("signup")}>
                  회원가입
                </button>
              </p>
            </form>
          ) : (
            <form className="auth-form" onSubmit={handleSignup}>
              <div className="auth-title">
                <p className="eyebrow">STEP 1. Create account</p>
                <h1>회원가입</h1>
                <p>필수 계정 정보와 선택 전공 정보를 바탕으로 개인 로드맵을 만듭니다.</p>
              </div>

              <div className={`auth-message${message ? " error" : ""}`} aria-live="assertive">
                {message}
              </div>

              <div className="auth-field-row">
                <label className="auth-field">
                  <span>이름 입력</span>
                  <input
                    type="text"
                    placeholder="예 : 안선주"
                    value={signupName}
                    onChange={(event) => setSignupName(event.target.value)}
                    required
                  />
                </label>
                <label className="auth-field">
                  <span>학번</span>
                  <input
                    type="text"
                    inputMode="numeric"
                    placeholder="예 : 202366247"
                    value={studentId}
                    onChange={(event) => setStudentId(event.target.value)}
                    required
                  />
                </label>
              </div>

              <label className="auth-field">
                <span>이메일 입력</span>
                <input
                  type="email"
                  placeholder="예 : dowon@pusan.ac.kr"
                  value={signupEmail}
                  onChange={(event) => setSignupEmail(event.target.value)}
                  required
                />
              </label>
              <label className="auth-field">
                <span>비밀번호 입력</span>
                <input
                  type="password"
                  placeholder="8자 이상 입력하세요"
                  value={signupPassword}
                  onChange={(event) => setSignupPassword(event.target.value)}
                  required
                />
              </label>
              <label className="auth-field">
                <span>학과 입력</span>
                <input
                  type="text"
                  placeholder="예 : 디자인학과"
                  value={department}
                  onChange={(event) => setDepartment(event.target.value)}
                />
              </label>
              <label className="auth-field">
                <span>진로 입력</span>
                <input
                  type="text"
                  placeholder="예 : 데이터사이언티스트"
                  value={careerGoal}
                  onChange={(event) => setCareerGoal(event.target.value)}
                />
              </label>

              <div className="auth-field-row">
                <label className="auth-field">
                  <span>부전공 입력</span>
                  <input
                    type="text"
                    placeholder="예 : 의류학과"
                    value={minorMajor}
                    onChange={(event) => setMinorMajor(event.target.value)}
                  />
                </label>
                <label className="auth-field">
                  <span>복수전공 입력</span>
                  <input
                    type="text"
                    placeholder="예 : 컴퓨터공학과"
                    value={dualMajor}
                    onChange={(event) => setDualMajor(event.target.value)}
                  />
                </label>
              </div>

              <button className="auth-submit" type="submit" disabled={isSignupSubmitting}>
                {isSignupSubmitting ? "가입 중..." : "다음"}
              </button>

              <p className="auth-switch">
                이미 계정이 있나요?{" "}
                <button type="button" onClick={() => setMode("login")}>
                  로그인
                </button>
              </p>
            </form>
          )}
        </div>
      </section>

      {mode === "login" ? (
        <ul className="auth-highlights">
          {loginHighlights.map((item) => (
            <li key={item.label}>
              <strong>{item.value}</strong>
              <span>{item.label}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </main>
  );
}
