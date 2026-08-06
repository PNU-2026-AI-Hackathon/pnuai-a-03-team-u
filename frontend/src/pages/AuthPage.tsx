import { useState } from "react";
import type { FormEvent } from "react";
import { ChevronDown } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { BrandMark } from "../components/layout/BrandMark";
import { SignupStepper } from "../components/auth/SignupStepper";
import { useAuth } from "../auth/AuthContext";
import type { AcademicProgramInput, AdmissionType } from "../api/auth";
import { PNU_EMAIL_DOMAIN, toPnuEmail } from "../api/auth";
import { getApiErrorMessage } from "../api/client";

type AuthMode = "login" | "signup";
type MessageKind = "error" | "success";

export function AuthPage() {
  const navigate = useNavigate();
  const { loginWithEmail, signupWithEmail } = useAuth();
  const [mode, setMode] = useState<AuthMode>("login");
  const [message, setMessage] = useState("");
  const [loginMessage, setLoginMessage] = useState("");
  const [loginMessageKind, setLoginMessageKind] = useState<MessageKind>("error");
  const [isLoginSubmitting, setIsLoginSubmitting] = useState(false);
  const [isSignupSubmitting, setIsSignupSubmitting] = useState(false);
  const [loginEmailId, setLoginEmailId] = useState("");
  const [loginPassword, setLoginPassword] = useState("");
  const [rememberLogin, setRememberLogin] = useState(false);
  const [signupPassword, setSignupPassword] = useState("");
  const [signupEmail, setSignupEmail] = useState("");
  const [signupName, setSignupName] = useState("");
  const [studentId, setStudentId] = useState("");
  const [admissionType, setAdmissionType] = useState<AdmissionType>("freshman");
  const [department, setDepartment] = useState("");
  const [primaryMajor, setPrimaryMajor] = useState("");
  const [careerGoal, setCareerGoal] = useState("");
  const [minorDepartment, setMinorDepartment] = useState("");
  const [minorMajor, setMinorMajor] = useState("");
  const [dualDepartment, setDualDepartment] = useState("");
  const [dualMajor, setDualMajor] = useState("");
  const [isAdditionalProgramsOpen, setIsAdditionalProgramsOpen] = useState(false);

  async function handleLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoginMessage("");
    setLoginMessageKind("error");
    setIsLoginSubmitting(true);
    try {
      await loginWithEmail(toPnuEmail(loginEmailId), loginPassword, rememberLogin);
      navigate("/", { replace: true });
    } catch (error) {
      setLoginMessage(getApiErrorMessage(error, "로그인에 실패했습니다. 입력한 정보를 확인해 주세요."));
    } finally {
      setIsLoginSubmitting(false);
    }
  }

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
    if (minorMajor.trim() && !minorDepartment.trim()) {
      setMessage("부전공 세부전공을 입력하려면 학과 또는 학부를 먼저 입력해주세요.");
      return;
    }
    if (dualMajor.trim() && !dualDepartment.trim()) {
      setMessage("복수전공 세부전공을 입력하려면 학과 또는 학부를 먼저 입력해주세요.");
      return;
    }

    const academicPrograms: AcademicProgramInput[] = [];
    if (department.trim()) {
      academicPrograms.push({
        department: department.trim(),
        major: primaryMajor.trim() || undefined,
        program_type: "primary",
      });
    }
    if (minorDepartment.trim()) {
      academicPrograms.push({
        department: minorDepartment.trim(),
        major: minorMajor.trim() || undefined,
        program_type: "minor",
      });
    }
    if (dualDepartment.trim()) {
      academicPrograms.push({
        department: dualDepartment.trim(),
        major: dualMajor.trim() || undefined,
        program_type: "dual",
      });
    }

    setIsSignupSubmitting(true);
    let isAccountCreated = false;
    try {
      const email = toPnuEmail(signupEmail);
      await signupWithEmail({
        email,
        password: signupPassword,
        name: signupName,
        student_id: studentId,
        admission_type: admissionType,
        school: "부산대학교",
        department: department || undefined,
        career_goal: careerGoal || undefined,
        academic_programs: academicPrograms,
      });
      isAccountCreated = true;
      await loginWithEmail(email, signupPassword, false);
      window.location.replace("/onboarding");
    } catch (error) {
      if (isAccountCreated) {
        setLoginEmailId("");
        setLoginPassword("");
        setLoginMessageKind("error");
        setLoginMessage("회원가입은 완료되었지만 자동 로그인에 실패했습니다. 직접 로그인해 주세요.");
        setMode("login");
      } else {
        setMessage(getApiErrorMessage(error, "회원가입에 실패했습니다. 입력한 정보를 확인해 주세요."));
      }
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
                <span>부산대 웹메일 입력</span>
                <div className="auth-email-field">
                  <input
                    type="text"
                    autoComplete="username"
                    placeholder="아이디를 입력하세요"
                    value={loginEmailId}
                    onChange={(event) => setLoginEmailId(event.target.value)}
                    required
                  />
                  <span className="auth-email-domain">{PNU_EMAIL_DOMAIN}</span>
                </div>
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
                <p className="eyebrow">Create account</p>
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

              <fieldset className="auth-field auth-choice">
                <legend>입학 구분</legend>
                <div className="auth-choice-options">
                  <label className={`auth-choice-option${admissionType === "freshman" ? " is-selected" : ""}`}>
                    <input
                      type="radio"
                      name="admission-type"
                      value="freshman"
                      checked={admissionType === "freshman"}
                      onChange={() => setAdmissionType("freshman")}
                    />
                    <span className="auth-choice-label">신입학</span>
                    <span className="auth-choice-hint">1학년부터 이수</span>
                  </label>
                  <label className={`auth-choice-option${admissionType === "transfer" ? " is-selected" : ""}`}>
                    <input
                      type="radio"
                      name="admission-type"
                      value="transfer"
                      checked={admissionType === "transfer"}
                      onChange={() => setAdmissionType("transfer")}
                    />
                    <span className="auth-choice-label">편입학</span>
                    <span className="auth-choice-hint">3학년부터 이수</span>
                  </label>
                </div>
              </fieldset>

              <label className="auth-field">
                <span>부산대 웹메일 입력</span>
                <div className="auth-email-field">
                  <input
                    type="text"
                    autoComplete="username"
                    placeholder="아이디를 입력하세요"
                    value={signupEmail}
                    onChange={(event) => setSignupEmail(event.target.value)}
                    required
                  />
                  <span className="auth-email-domain">{PNU_EMAIL_DOMAIN}</span>
                </div>
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
                <span>학과 또는 학부 입력</span>
                <input
                  type="text"
                  placeholder="예 : 의생명융합공학부"
                  value={department}
                  onChange={(event) => setDepartment(event.target.value)}
                  required
                />
              </label>
              <label className="auth-field">
                <span>세부전공 입력 (선택)</span>
                <input
                  type="text"
                  placeholder="예 : 데이터사이언스전공"
                  value={primaryMajor}
                  onChange={(event) => setPrimaryMajor(event.target.value)}
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

              <section className={`auth-program-options${isAdditionalProgramsOpen ? " is-open" : ""}`}>
                <button
                  className="auth-program-toggle"
                  type="button"
                  aria-expanded={isAdditionalProgramsOpen}
                  aria-controls="additional-program-fields"
                  onClick={() => setIsAdditionalProgramsOpen((isOpen) => !isOpen)}
                >
                  <span>부전공·복수전공 입력</span>
                  <small>선택</small>
                  <ChevronDown size={18} aria-hidden="true" />
                </button>

                {isAdditionalProgramsOpen ? (
                  <div className="auth-program-grid" id="additional-program-fields">
                    <label className="auth-field">
                      <span>부전공 학과 또는 학부 입력</span>
                      <input
                        type="text"
                        placeholder="예 : 의류학과"
                        value={minorDepartment}
                        onChange={(event) => setMinorDepartment(event.target.value)}
                      />
                    </label>
                    <label className="auth-field">
                      <span>부전공 세부전공 입력 (선택)</span>
                      <input
                        type="text"
                        placeholder="예 : 패션디자인전공"
                        value={minorMajor}
                        onChange={(event) => setMinorMajor(event.target.value)}
                      />
                    </label>
                    <label className="auth-field">
                      <span>복수전공 학과 또는 학부 입력</span>
                      <input
                        type="text"
                        placeholder="예 : 정보컴퓨터공학부"
                        value={dualDepartment}
                        onChange={(event) => setDualDepartment(event.target.value)}
                      />
                    </label>
                    <label className="auth-field">
                      <span>복수전공 세부전공 입력 (선택)</span>
                      <input
                        type="text"
                        placeholder="예 : 컴퓨터공학전공"
                        value={dualMajor}
                        onChange={(event) => setDualMajor(event.target.value)}
                      />
                    </label>
                  </div>
                ) : null}
              </section>

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

    </main>
  );
}
