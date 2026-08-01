import { Check } from "lucide-react";

const steps = ["계정 정보", "학사정보 불러오기", "완료"];

/** 회원가입 3단계 진행 표시. current는 1부터 센다. */
export function SignupStepper({ current }: { current: number }) {
  return (
    <ol className="signup-stepper" aria-label="회원가입 진행 단계">
      {steps.map((label, index) => {
        const step = index + 1;
        const state = step < current ? "done" : step === current ? "current" : "todo";
        return (
          <li className={`signup-step is-${state}`} key={label}>
            <span className="signup-step-badge" aria-hidden="true">
              {state === "done" ? <Check size={14} /> : step}
            </span>
            <span className="signup-step-label">{label}</span>
            {step < steps.length ? <span className="signup-step-line" aria-hidden="true" /> : null}
          </li>
        );
      })}
    </ol>
  );
}
