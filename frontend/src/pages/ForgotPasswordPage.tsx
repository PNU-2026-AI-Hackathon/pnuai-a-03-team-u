import { useState } from "react";
import type { FormEvent } from "react";
import { ArrowLeft, Mail } from "lucide-react";
import { Link } from "react-router-dom";
import { BrandMark } from "../components/layout/BrandMark";

export function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isSubmitted, setIsSubmitted] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsSubmitting(true);

    // Replace this delay with the password-reset request API when it is available.
    await new Promise((resolve) => window.setTimeout(resolve, 700));

    setIsSubmitting(false);
    setIsSubmitted(true);
  }

  return (
    <main className="auth-page password-reset-page">
      <section className="auth-brand-panel password-reset-brand-panel">
        <Link className="auth-brand" to="/auth">
          <BrandMark id="plan-u-face-password-reset" />
          <span>
            Plan <strong>U</strong>
          </span>
        </Link>
        <div>
          <p className="eyebrow">Account Recovery</p>
          <h1>계정에 다시 접속할 수 있도록 도와드릴게요.</h1>
          <p>가입할 때 사용한 이메일로 비밀번호 재설정 안내를 보내드립니다.</p>
        </div>
        <Link className="password-reset-back" to="/auth">
          <ArrowLeft size={16} aria-hidden="true" />
          로그인으로 돌아가기
        </Link>
      </section>

      <section className="auth-card password-reset-card">
        <form className="auth-form active" onSubmit={handleSubmit}>
          <div className="password-reset-icon" aria-hidden="true">
            <Mail size={24} />
          </div>
          <div className="auth-title">
            <p className="eyebrow">Reset Password</p>
            <h2>비밀번호 찾기</h2>
            <p>가입한 이메일 주소를 입력해 주세요.</p>
          </div>
          <label>
            <span>이메일</span>
            <input
              type="email"
              placeholder="예: dowon@school.ac.kr"
              value={email}
              onChange={(event) => {
                setEmail(event.target.value);
                setIsSubmitted(false);
              }}
              autoComplete="email"
              required
            />
          </label>
          <div className={`auth-message${isSubmitted ? " success" : ""}`} aria-live="polite">
            입력한 이메일이 가입된 계정이라면 비밀번호 재설정 안내가 발송됩니다.
          </div>
          <button className="auth-submit" type="submit" disabled={isSubmitting}>
            {isSubmitting ? "확인 중..." : "재설정 안내 받기"}
          </button>
          <Link className="password-reset-mobile-back" to="/auth">
            <ArrowLeft size={15} aria-hidden="true" />
            로그인으로 돌아가기
          </Link>
        </form>
      </section>
    </main>
  );
}
