import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { BrandMark } from "../components/layout/BrandMark";
import { useAuth } from "../auth/AuthContext";
import type { AcademicProgramInput } from "../api/auth";
import { getApiErrorMessage } from "../api/client";

type AuthMode = "login" | "signup";
type MessageKind = "error" | "success";

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

  async function handleSignup(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage("");

    if (signupPassword.length < 8) {
      setMessage("400 Bad Request · 비밀번호는 8자 이상이어야 합니다.");
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
      setLoginStudentId(studentId.trim());
      setLoginPassword("");
      setLoginMessage("회원가입이 완료되었습니다. 로그인해 주세요.");
      setLoginMessageKind("success");
      setMode("login");
    } catch (error) {
      setMessage(getApiErrorMessage(error, "회원가입에 실패했습니다. 입력한 정보를 확인해 주세요."));
    } finally {
      setIsSignupSubmitting(false);
    }
  }

  return (
    <main className="auth-page">
      <section className="auth-brand-panel">
        <Link className="auth-brand" to="/">
          <BrandMark id="plan-u-face-auth" />
          <span>
            Plan <strong>U</strong>
          </span>
        </Link>
        <div>
          <p className="eyebrow">Student Growth OS</p>
          <h1>내 학업 데이터와 성장 로드맵을 한 곳에서 관리하세요.</h1>
          <p>교과 활동, 비교과 활동, 자격증, 어학 성적, 졸업요건을 개인별로 연결합니다.</p>
        </div>
        <div className="auth-preview">
          <div>
            <span>졸업요건</span>
            <strong>112 / 130학점</strong>
          </div>
          <div>
            <span>비교과 활동</span>
            <strong>6건 관리</strong>
          </div>
          <div>
            <span>현재 학기</span>
            <strong>3학년 1학기</strong>
          </div>
        </div>
      </section>

      <section className="auth-card" data-auth-mode={mode}>
        <div className="auth-tabs" aria-label="인증 방식 선택">
          <button className={mode === "login" ? "selected" : ""} type="button" onClick={() => setMode("login")}>
            로그인
          </button>
          <button className={mode === "signup" ? "selected" : ""} type="button" onClick={() => setMode("signup")}>
            회원가입
          </button>
        </div>

        <form className={`auth-form${mode === "login" ? " active" : ""}`} onSubmit={handleLogin}>
          <div className="auth-title">
            <p className="eyebrow">Welcome Back</p>
            <h2>로그인</h2>
            <p>Plan U 계정으로 내 정보를 이어서 확인합니다.</p>
          </div>
          <label>
            <span>학번</span>
            <input
              type="text"
              inputMode="numeric"
              autoComplete="username"
              placeholder="예: 202312345"
              value={loginStudentId}
              onChange={(event) => setLoginStudentId(event.target.value)}
              required
            />
          </label>
          <label>
            <span>비밀번호</span>
            <input
              type="password"
              autoComplete="current-password"
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
              /> 로그인 유지
            </label>
            <Link to="/forgot-password">비밀번호 찾기</Link>
          </div>
          <button className="auth-submit" type="submit" disabled={isLoginSubmitting}>
            {isLoginSubmitting ? "로그인 중..." : "로그인"}
          </button>
        </form>

        <form className={`auth-form${mode === "signup" ? " active" : ""}`} onSubmit={handleSignup}>
          <div className="auth-title">
            <p className="eyebrow">Create Account</p>
            <h2>회원가입</h2>
            <p>필수 계정 정보와 선택 전공 정보를 바탕으로 개인 로드맵을 만듭니다.</p>
          </div>
          <div className={`auth-message${message ? " error" : ""}`} aria-live="assertive">
            {message}
          </div>
          <label>
            <span>이메일</span>
            <input type="email" placeholder="예: dowon@school.ac.kr" value={signupEmail} onChange={(event) => setSignupEmail(event.target.value)} required />
          </label>
          <label>
            <span>비밀번호</span>
            <input type="password" placeholder="8자 이상 입력하세요" value={signupPassword} onChange={(event) => setSignupPassword(event.target.value)} required />
          </label>
          <label>
            <span>이름</span>
            <input type="text" placeholder="이름을 입력하세요" value={signupName} onChange={(event) => setSignupName(event.target.value)} required />
          </label>
          <label>
            <span>학번</span>
            <input type="text" inputMode="numeric" placeholder="예: 202312345" value={studentId} onChange={(event) => setStudentId(event.target.value)} required />
          </label>
          <label>
            <span>학과</span>
            <input type="text" placeholder="예: 의생명융합공학부" value={department} onChange={(event) => setDepartment(event.target.value)} />
          </label>
          <label>
            <span>
              진로 <em>선택</em>
            </span>
            <input type="text" placeholder="예: 데이터 사이언티스트" value={careerGoal} onChange={(event) => setCareerGoal(event.target.value)} />
          </label>
          <div className="auth-repeat-group">
            <div className="repeat-head">
              <span>
                부전공 <em>선택</em>
              </span>
            </div>
            <label>
              <input type="text" placeholder="예: 의류학과" value={minorMajor} onChange={(event) => setMinorMajor(event.target.value)} />
            </label>
          </div>
          <div className="auth-repeat-group">
            <div className="repeat-head">
              <span>
                복수전공 <em>선택</em>
              </span>
            </div>
            <label>
              <input type="text" placeholder="예: 컴퓨터공학과" value={dualMajor} onChange={(event) => setDualMajor(event.target.value)} />
            </label>
          </div>
          <button className="auth-submit signup-submit" type="submit" disabled={isSignupSubmitting}>
            {isSignupSubmitting ? "가입 중..." : "회원가입"}
          </button>
        </form>
      </section>
    </main>
  );
}
