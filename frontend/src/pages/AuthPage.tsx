import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import axios from "axios";
import { BrandMark } from "../components/layout/BrandMark";
import { useAuth } from "../auth/AuthContext";
import { isMockAuthEnabled } from "../api/auth";
import type { AcademicProgram } from "../api/auth";

type AuthMode = "login" | "signup";

export function AuthPage() {
  const navigate = useNavigate();
  const { loginWithEmail, signupWithEmail } = useAuth();
  const [mode, setMode] = useState<AuthMode>("login");
  const [message, setMessage] = useState("");
  const [loginMessage, setLoginMessage] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [loginEmail, setLoginEmail] = useState("");
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

  function getErrorMessage(error: unknown) {
    if (axios.isAxiosError(error)) {
      const detail = error.response?.data?.detail;
      if (typeof detail === "string") return detail;
      if (Array.isArray(detail)) return detail.map((item) => item.msg ?? JSON.stringify(item)).join(", ");
      return error.message;
    }
    return "요청 중 오류가 발생했습니다.";
  }

  async function handleLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoginMessage("");
    setIsSubmitting(true);
    try {
      await loginWithEmail(loginEmail, loginPassword, rememberLogin);
      navigate("/", { replace: true });
    } catch (error) {
      setLoginMessage(getErrorMessage(error));
    } finally {
      setIsSubmitting(false);
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

    const academicPrograms: AcademicProgram[] = [];
    if (department.trim()) {
      academicPrograms.push({ major: department.trim(), program_type: "primary" });
    }
    if (minorMajor.trim()) {
      academicPrograms.push({ major: minorMajor.trim(), program_type: "minor" });
    }
    if (dualMajor.trim()) {
      academicPrograms.push({ major: dualMajor.trim(), program_type: "dual" });
    }

    setIsSubmitting(true);
    try {
      await signupWithEmail({
        email: signupEmail,
        password: signupPassword,
        name: signupName,
        student_id: studentId || undefined,
        school: "부산대학교",
        department: department || undefined,
        career_goal: careerGoal || undefined,
        academic_programs: academicPrograms,
      });
      navigate("/");
    } catch (error) {
      setMessage(getErrorMessage(error));
    } finally {
      setIsSubmitting(false);
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
            <span>{isMockAuthEnabled ? "아이디" : "이메일"}</span>
            <input
              type={isMockAuthEnabled ? "text" : "email"}
              placeholder={isMockAuthEnabled ? undefined : "이메일을 입력하세요"}
              value={loginEmail}
              onChange={(event) => setLoginEmail(event.target.value)}
              required
            />
          </label>
          <label>
            <span>비밀번호</span>
            <input
              type="password"
              placeholder={isMockAuthEnabled ? undefined : "비밀번호를 입력하세요"}
              value={loginPassword}
              onChange={(event) => setLoginPassword(event.target.value)}
              required
            />
          </label>
          <div className={`auth-message${loginMessage ? " error" : ""}`} aria-live="polite">
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
          <button className="auth-submit" type="submit" disabled={isSubmitting}>
            {isSubmitting ? "로그인 중..." : "로그인"}
          </button>
        </form>

        <form className={`auth-form${mode === "signup" ? " active" : ""}`} onSubmit={handleSignup}>
          <div className="auth-title">
            <p className="eyebrow">Create Account</p>
            <h2>회원가입</h2>
            <p>필수 계정 정보와 선택 전공 정보를 바탕으로 개인 로드맵을 만듭니다.</p>
          </div>
          <div className={`auth-message${message.includes("Bad") || message.includes("Conflict") ? " error" : message ? " success" : ""}`} aria-live="polite">
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
            <input type="text" inputMode="numeric" placeholder="학번을 입력하세요" value={studentId} onChange={(event) => setStudentId(event.target.value)} />
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
          <button className="auth-submit signup-submit" type="submit" disabled={isSubmitting}>
            {isSubmitting ? "가입 중..." : "회원가입"}
          </button>
        </form>
      </section>
    </main>
  );
}
