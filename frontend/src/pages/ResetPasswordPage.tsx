import { useState } from "react";
import type { FormEvent } from "react";
import { ArrowLeft, Check } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import { BrandMark } from "../components/layout/BrandMark";
import { confirmPasswordReset } from "../api/auth";
import { getApiErrorMessage } from "../api/client";

/**
 * 메일 링크로 열리는 비밀번호 재설정 화면. `/reset-password?token=...`
 * 토큰 검증은 전적으로 서버가 하고, 여기서는 형식(8자 이상)만 미리 걸러준다.
 */
export function ResetPasswordPage() {
  const [searchParams] = useSearchParams();
  const token = searchParams.get("token") ?? "";
  const [password, setPassword] = useState("");
  const [passwordConfirm, setPasswordConfirm] = useState("");
  const [isDone, setIsDone] = useState(false);
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");

    if (password.length < 8) {
      setError("비밀번호는 8자 이상이어야 합니다.");
      return;
    }
    if (password !== passwordConfirm) {
      setError("두 비밀번호가 서로 다릅니다.");
      return;
    }

    setIsSubmitting(true);
    try {
      await confirmPasswordReset(token, password);
      setIsDone(true);
    } catch (confirmError) {
      setError(
        getApiErrorMessage(confirmError, "비밀번호를 바꾸지 못했습니다. 링크를 다시 요청해 주세요."),
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main className="auth-screen route-view">
      <section className="auth-shell">
        <Link className="auth-logo" to="/auth" aria-label="로그인으로">
          <BrandMark id="plan-u-face-reset-confirm" />
          <span>
            Plan <strong>U</strong>
          </span>
        </Link>

        <div className="auth-panel">
          {isDone ? (
            <div className="onboarding-done">
              <span className="onboarding-done-mark" aria-hidden="true">
                <Check size={20} />
              </span>
              <h1>비밀번호가 변경되었습니다</h1>
              <p>새 비밀번호로 다시 로그인해 주세요.</p>
              <Link className="auth-submit" to="/auth">
                로그인하러 가기
              </Link>
            </div>
          ) : !token ? (
            <div className="auth-title reset-title">
              <h1>링크가 올바르지 않습니다</h1>
              <p>메일에 담긴 주소로 다시 들어와 주세요. 링크는 30분 동안만 유효합니다.</p>
              <Link className="auth-submit" to="/forgot-password">
                재설정 링크 다시 받기
              </Link>
            </div>
          ) : (
            <form className="auth-form" onSubmit={handleSubmit}>
              <div className="auth-title reset-title">
                <h1>새 비밀번호를 입력하세요.</h1>
                <p>8자 이상으로 설정해 주세요.</p>
              </div>

              <label className="auth-field">
                <span>새 비밀번호</span>
                <input
                  type="password"
                  autoComplete="new-password"
                  placeholder="8자 이상 입력하세요"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  required
                />
              </label>
              <label className="auth-field">
                <span>새 비밀번호 확인</span>
                <input
                  type="password"
                  autoComplete="new-password"
                  placeholder="한 번 더 입력하세요"
                  value={passwordConfirm}
                  onChange={(event) => setPasswordConfirm(event.target.value)}
                  required
                />
              </label>

              <div className={`auth-message${error ? " error" : ""}`} aria-live="assertive">
                {error}
              </div>

              <button className="auth-submit" type="submit" disabled={isSubmitting}>
                {isSubmitting ? "변경 중" : "비밀번호 변경"}
              </button>
            </form>
          )}
        </div>

        <Link className="reset-back" to="/auth">
          <ArrowLeft size={15} aria-hidden="true" />
          로그인으로 돌아가기
        </Link>
      </section>
    </main>
  );
}
