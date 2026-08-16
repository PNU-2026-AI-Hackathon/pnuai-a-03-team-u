import { useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { ChevronDown } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { BrandMark } from "../components/layout/BrandMark";
import { FieldAutocomplete } from "../components/auth/FieldAutocomplete";
import type { AutocompleteOption } from "../components/auth/FieldAutocomplete";
import { searchDepartments } from "../api/departments";
import type { DepartmentSearchResult } from "../api/departments";
import { SignupStepper } from "../components/auth/SignupStepper";
import { useAuth } from "../auth/AuthContext";
import type { AcademicProgramInput, AdmissionType } from "../api/auth";
import { PNU_EMAIL_DOMAIN, toPnuEmail } from "../api/auth";
import { getApiErrorMessage } from "../api/client";
import { enrollTrack, previewTracks } from "../api/tracks";
import type { TrackPreview } from "../api/tracks";

type AuthMode = "login" | "signup";
type MessageKind = "error" | "success";

/**
 * 학과/학부 자동완성 후보. 입력이 멈추면 검색한다.
 *
 * 자동완성이 실패해도 입력은 계속할 수 있어야 하므로 오류를 삼킨다 —
 * 후보가 안 뜨는 것과 가입이 막히는 것은 다른 문제다.
 */
function useDepartmentOptions(query: string) {
  const [results, setResults] = useState<DepartmentSearchResult[]>([]);

  useEffect(() => {
    let cancelled = false;
    const timer = window.setTimeout(() => {
      void searchDepartments(query.trim(), 8)
        .then((data) => {
          if (!cancelled) setResults(data);
        })
        .catch(() => undefined);
    }, 200);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [query]);

  return results;
}

function toDepartmentOptions(results: DepartmentSearchResult[]): AutocompleteOption[] {
  return results.map((item) => ({ value: item.name, hint: item.college }));
}

/**
 * 고른 학과에 속한 전공만 후보로 내놓는다.
 *
 * 검색어가 학과명과 정확히 같을 때만 매칭되는데, 학과 후보를 고르면 입력값이
 * 정식 명칭으로 채워지므로 자연스럽게 걸린다. 직접 타이핑해도 철자가 맞으면 뜬다.
 */
function majorOptionsFor(
  results: DepartmentSearchResult[],
  departmentName: string,
  typed: string,
): AutocompleteOption[] {
  const matched = results.find((item) => item.name === departmentName.trim());
  if (!matched) return [];
  const keyword = typed.trim();
  return matched.majors
    .filter((major) => !keyword || major.includes(keyword))
    .map((major) => ({ value: major, hint: matched.name }));
}

/** {min:12, max:15} → "12~15", {min:15, max:15} → "15". 값이 없으면 안내용 기본 범위. */
function formatCreditRange(range: { min?: number; max?: number } | undefined, fallback: string) {
  const min = range?.min;
  const max = range?.max;
  if (min == null && max == null) return fallback;
  if (min != null && max != null) return min === max ? String(min) : `${min}~${max}`;
  return String(min ?? max);
}

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

  // 대상 학과를 고르면 뜨는 AI융합트랙 홍보 카드. 트랙은 학과에 1:1이라
  // 고르는 UI가 아니라 안내 + 체크(가입 직후 이수 체크 시작)로 충분하다.
  const [trackPreview, setTrackPreview] = useState<TrackPreview | null>(null);
  const [wantsTrack, setWantsTrack] = useState(false);

  // 학과 3개(주전공/부전공/복수전공)는 각자 따로 검색한다.
  const primaryResults = useDepartmentOptions(department);
  const minorResults = useDepartmentOptions(minorDepartment);
  const dualResults = useDepartmentOptions(dualDepartment);

  useEffect(() => {
    const name = department.trim();
    if (!name) {
      setTrackPreview(null);
      setWantsTrack(false);
      return;
    }
    let cancelled = false;
    // 서버가 정식 학과명 완전 일치로만 응답하므로 타이핑 중간값은 빈 배열이 온다.
    const timer = window.setTimeout(() => {
      previewTracks(name)
        .then((previews) => {
          if (cancelled) return;
          setTrackPreview(previews[0] ?? null);
          if (!previews.length) setWantsTrack(false);
        })
        .catch(() => {
          if (!cancelled) setTrackPreview(null);
        });
    }, 250);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [department]);

  const primaryMajorOptions = useMemo(
    () => majorOptionsFor(primaryResults, department, primaryMajor),
    [primaryResults, department, primaryMajor],
  );
  const minorMajorOptions = useMemo(
    () => majorOptionsFor(minorResults, minorDepartment, minorMajor),
    [minorResults, minorDepartment, minorMajor],
  );
  const dualMajorOptions = useMemo(
    () => majorOptionsFor(dualResults, dualDepartment, dualMajor),
    [dualResults, dualDepartment, dualMajor],
  );

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
      if (wantsTrack && trackPreview) {
        // 트랙 등록 실패가 가입 완주를 막으면 안 된다 — 내 정보에서 언제든
        // 다시 시작할 수 있으므로 조용히 넘어간다.
        await enrollTrack(trackPreview.major_id).catch(() => undefined);
      }
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
      <section className={`auth-shell${mode === "signup" ? " is-signup is-wide" : ""}`}>
        <Link className="auth-logo" to="/" aria-label="Plan U 홈">
          <BrandMark id="plan-u-face-auth" />
          <span>
            Plan <strong>U</strong>
          </span>
        </Link>

        {mode === "signup" ? <SignupStepper current={1} /> : null}

        {/* 로그인은 단일 패널, 회원가입은 스텝 2와 같은 와이드 2컬럼. 화면 전환은
            양쪽 모두 폼 하단 링크("회원가입"/"로그인")가 담당 — 탭은 두지 않는다. */}
        {mode === "login" ? (
          <div className="auth-panel">
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
          </div>
          ) : (
            <form className="onboarding-columns signup-columns" onSubmit={handleSignup}>
              <div className="auth-panel">
              <div className="auth-title">
                <p className="eyebrow">STEP 1 · ACCOUNT</p>
                <h1>계정 정보 입력</h1>
                <p>
                  필수 계정 정보를 입력합니다.
                  <br />
                  다음 단계에서 학사정보를 자동으로 불러옵니다.
                </p>
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
              </div>

              <div className="auth-panel">
              <div className="auth-title">
                <p className="eyebrow">Major &amp; Career</p>
                <h2>전공 · 진로 정보</h2>
                <p>
                  학과를 입력하면 세부전공 선택이 열립니다.
                  <br />
                  전공 정보는 졸업요건 분석과 로드맵의 기준이 돼요.
                </p>
              </div>
              <FieldAutocomplete
                label="학과 또는 학부 입력"
                placeholder="예 : 의생명융합공학부"
                value={department}
                onChange={(next) => {
                  setDepartment(next);
                  // 학과를 바꾸면 이전 학과의 전공은 더 이상 맞지 않는다.
                  if (next.trim() !== department.trim()) setPrimaryMajor("");
                }}
                options={toDepartmentOptions(primaryResults)}
                required
              />
              <FieldAutocomplete
                label="세부전공 입력 (선택)"
                placeholder="예 : 데이터사이언스전공"
                value={primaryMajor}
                onChange={setPrimaryMajor}
                options={primaryMajorOptions}
                minChars={0}
                emptyHint={
                  department.trim() ? "이 학부는 세부전공 구분이 없습니다" : "학부를 먼저 고르세요"
                }
              />
              {trackPreview ? (
                <div className="auth-track-card">
                  <p className="auth-track-title">
                    🎓 {trackPreview.department_name}는 <strong>{trackPreview.track_name}</strong> 대상 학과예요
                  </p>
                  <p className="auth-track-desc">
                    학과전공 {formatCreditRange(trackPreview.dept_credits, "12~15")}학점 +
                    AI융합공통 {formatCreditRange(trackPreview.ai_common_credits, "6~9")}학점,
                    총 {trackPreview.total_credits}학점 인증 과정입니다. 이수 중이라면 체크해 두세요 —
                    남은 학점을 자동으로 계산해 드려요.
                  </p>
                  <label className="auth-track-check">
                    <input
                      type="checkbox"
                      checked={wantsTrack}
                      onChange={(event) => setWantsTrack(event.target.checked)}
                    />
                    <span>이 트랙을 이수하고 있어요 (내 정보에서 언제든 해제 가능)</span>
                  </label>
                </div>
              ) : null}
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
                    <FieldAutocomplete
                      label="부전공 학과 또는 학부 입력"
                      placeholder="예 : 의류학과"
                      value={minorDepartment}
                      onChange={(next) => {
                        setMinorDepartment(next);
                        if (next.trim() !== minorDepartment.trim()) setMinorMajor("");
                      }}
                      options={toDepartmentOptions(minorResults)}
                    />
                    <FieldAutocomplete
                      label="부전공 세부전공 입력 (선택)"
                      placeholder="예 : 패션디자인전공"
                      value={minorMajor}
                      onChange={setMinorMajor}
                      options={minorMajorOptions}
                      minChars={0}
                      emptyHint={
                        minorDepartment.trim()
                          ? "이 학부는 세부전공 구분이 없습니다"
                          : "학부를 먼저 고르세요"
                      }
                    />
                    <FieldAutocomplete
                      label="복수전공 학과 또는 학부 입력"
                      placeholder="예 : 정보컴퓨터공학부"
                      value={dualDepartment}
                      onChange={(next) => {
                        setDualDepartment(next);
                        if (next.trim() !== dualDepartment.trim()) setDualMajor("");
                      }}
                      options={toDepartmentOptions(dualResults)}
                    />
                    <FieldAutocomplete
                      label="복수전공 세부전공 입력 (선택)"
                      placeholder="예 : 컴퓨터공학전공"
                      value={dualMajor}
                      onChange={setDualMajor}
                      options={dualMajorOptions}
                      minChars={0}
                      emptyHint={
                        dualDepartment.trim()
                          ? "이 학부는 세부전공 구분이 없습니다"
                          : "학부를 먼저 고르세요"
                      }
                    />
                  </div>
                ) : null}
              </section>
              </div>

              <div className="signup-columns-footer">
                <div className={`auth-message${message ? " error" : ""}`} aria-live="assertive">
                  {message}
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
              </div>
            </form>
          )}
      </section>

    </main>
  );
}
