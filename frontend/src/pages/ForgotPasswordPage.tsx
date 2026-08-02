import { useState } from "react";
import type { FormEvent } from "react";
import { ArrowLeft, Check } from "lucide-react";
import { Link } from "react-router-dom";
import { BrandMark } from "../components/layout/BrandMark";

type Step = 1 | 2 | 3 | 4;
type Lookup = "studentId" | "email";

/**
 * 비밀번호 찾기 (Figma 266:914). 학번 → 이름 확인 → 새 비밀번호 순서다.
 * 서버에 비밀번호 재설정 엔드포인트가 아직 없어서 화면 흐름만 동작한다.
 */
export function ForgotPasswordPage() {
  const [step, setStep] = useState<Step>(1);
  const [lookup, setLookup] = useState<Lookup>("studentId");
  const [identifier, setIdentifier] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");

  const identifierLabel = lookup === "studentId" ? "학번 입력" : "이메일 입력";
  const identifierHint = lookup === "studentId" ? "학번을 입력해 주세요." : "이메일을 입력해 주세요.";

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");

    if (step === 3 && password.length < 8) {
      setError("비밀번호는 8자 이상이어야 합니다.");
      return;
    }

    setStep((current) => (current === 4 ? current : ((current + 1) as Step)));
  }

  function switchLookup() {
    setLookup((current) => (current === "studentId" ? "email" : "studentId"));
    setIdentifier("");
    setError("");
  }

  return (
    <main className="auth-screen">
      <section className="auth-shell">
        <Link className="auth-logo" to="/auth" aria-label="로그인으로">
          <BrandMark id="plan-u-face-password-reset" />
          <span>
            Plan <strong>U</strong>
          </span>
        </Link>

        <div className="auth-panel">
          {step === 4 ? (
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
          ) : (
            <form className="auth-form" onSubmit={handleSubmit}>
              <div className="auth-title reset-title">
                <h1>{step === 3 ? "새 비밀번호를 입력하세요." : "비밀번호 찾기"}</h1>
                {step === 1 ? <p>{identifierHint}</p> : null}
                {step === 2 ? <p>이름을 입력해주세요.</p> : null}
              </div>

              {step === 1 ? (
                <label className="auth-field">
                  <span>{identifierLabel}</span>
                  <input
                    type={lookup === "studentId" ? "text" : "email"}
                    inputMode={lookup === "studentId" ? "numeric" : "email"}
                    placeholder={lookup === "studentId" ? "예 : 202366247" : "예 : dowon@pusan.ac.kr"}
                    value={identifier}
                    onChange={(event) => setIdentifier(event.target.value)}
                    required
                  />
                </label>
              ) : null}

              {step === 2 ? (
                <>
                  <label className="auth-field is-locked">
                    <span>{lookup === "studentId" ? "학번" : "이메일"}</span>
                    <input type="text" value={identifier} readOnly />
                  </label>
                  <label className="auth-field">
                    <span>이름</span>
                    <input
                      type="text"
                      placeholder="예 : 안선주"
                      value={name}
                      onChange={(event) => setName(event.target.value)}
                      required
                    />
                  </label>
                </>
              ) : null}

              {step === 3 ? (
                <label className="auth-field">
                  <span>비밀번호</span>
                  <input
                    type="password"
                    placeholder="8자 이상 입력하세요"
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    autoComplete="new-password"
                    required
                  />
                </label>
              ) : null}

              <div className={`auth-message${error ? " error" : ""}`} aria-live="assertive">
                {error}
              </div>

              <div className="reset-actions">
                {step < 3 ? (
                  <button className="reset-switch" type="button" onClick={switchLookup}>
                    {lookup === "studentId" ? "이메일을 입력해 비밀번호 찾기" : "학번을 입력해 비밀번호 찾기"}
                  </button>
                ) : (
                  <span />
                )}
                <button className="auth-submit" type="submit">
                  다음
                </button>
              </div>
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
