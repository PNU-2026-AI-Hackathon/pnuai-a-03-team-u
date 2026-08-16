import { useState } from "react";
import type { FormEvent } from "react";
import { ArrowLeft, Check } from "lucide-react";
import { Link } from "react-router-dom";
import { BrandMark } from "../components/layout/BrandMark";
import { PNU_EMAIL_DOMAIN, requestPasswordReset, toPnuEmail } from "../api/auth";
import { getApiErrorMessage } from "../api/client";

/**
 * 비밀번호 찾기 — 웹메일 → 이름 확인 → 재설정 링크 발송.
 *
 * 시안(266:914)은 "학번 → 이름 → 새 비밀번호"로 화면에서 바로 바꾸는 흐름이었지만,
 * 학번과 이름은 둘 다 사실상 공개 정보라 그것만으로 남의 비밀번호를 바꿀 수 있다.
 * 7/3 회의 주제 4(웹메일 로그인)에 맞춰, 이름 확인은 그대로 두되 실제 본인확인은
 * 메일 수신으로 한다. 새 비밀번호 입력은 메일 링크로 열리는 /reset-password 에서 한다.
 */
export function ForgotPasswordPage() {
  const [step, setStep] = useState<1 | 2>(1);
  const [emailId, setEmailId] = useState("");
  const [name, setName] = useState("");
  const [isSent, setIsSent] = useState(false);
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");

    if (step === 1) {
      setStep(2);
      return;
    }

    setIsSubmitting(true);
    try {
      await requestPasswordReset(toPnuEmail(emailId), name);
      setIsSent(true);
    } catch (requestError) {
      setError(getApiErrorMessage(requestError, "요청에 실패했습니다. 잠시 후 다시 시도해 주세요."));
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main className="auth-screen route-view">
      <section className="auth-shell">
        <Link className="auth-logo" to="/auth" aria-label="로그인으로">
          <BrandMark id="plan-u-face-password-reset" />
          <span>
            Plan <strong>U</strong>
          </span>
        </Link>

        <div className="auth-panel">
          {isSent ? (
            <div className="onboarding-done">
              <span className="onboarding-done-mark" aria-hidden="true">
                <Check size={20} />
              </span>
              <h1>메일을 보냈습니다</h1>
              <p>
                {toPnuEmail(emailId)} 으로 재설정 링크를 보냈습니다. 30분 안에 링크를 눌러 새
                비밀번호를 설정해 주세요.
              </p>
              <p className="reset-hint">
                메일이 오지 않는다면 스팸함을 확인하시고, 가입하지 않은 주소는 아닌지 확인해 주세요.
              </p>
              <Link className="auth-submit" to="/auth">
                로그인하러 가기
              </Link>
            </div>
          ) : (
            <form className="auth-form" onSubmit={handleSubmit}>
              <div className="auth-title reset-title">
                <h1>비밀번호 찾기</h1>
                <p>
                  {step === 1
                    ? "가입한 부산대 웹메일을 입력해 주세요."
                    : "이름을 입력해 주세요. 계정 정보와 일치하면 메일을 보내드립니다."}
                </p>
              </div>

              {step === 1 ? (
                <label className="auth-field">
                  <span>부산대 웹메일 입력</span>
                  <div className="auth-email-field">
                    <input
                      type="text"
                      autoComplete="username"
                      placeholder="아이디를 입력하세요"
                      value={emailId}
                      onChange={(event) => setEmailId(event.target.value)}
                      required
                    />
                    <span className="auth-email-domain">{PNU_EMAIL_DOMAIN}</span>
                  </div>
                </label>
              ) : (
                <>
                  <label className="auth-field is-locked">
                    <span>부산대 웹메일</span>
                    <input type="text" value={toPnuEmail(emailId)} readOnly />
                  </label>
                  <label className="auth-field">
                    <span>이름</span>
                    <input
                      type="text"
                      autoComplete="name"
                      placeholder="예 : 이도원"
                      value={name}
                      onChange={(event) => setName(event.target.value)}
                      required
                    />
                  </label>
                </>
              )}

              <div className={`auth-message${error ? " error" : ""}`} aria-live="assertive">
                {error}
              </div>

              <div className="reset-actions">
                {step === 2 ? (
                  <button
                    className="reset-switch"
                    type="button"
                    onClick={() => {
                      setStep(1);
                      setError("");
                    }}
                  >
                    웹메일 다시 입력
                  </button>
                ) : (
                  <span />
                )}
                <button className="auth-submit" type="submit" disabled={isSubmitting}>
                  {step === 1 ? "다음" : isSubmitting ? "보내는 중" : "재설정 링크 보내기"}
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
