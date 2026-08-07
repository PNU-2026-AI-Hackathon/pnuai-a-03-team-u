import { useEffect, useId, useRef, useState } from "react";
import type { KeyboardEvent } from "react";

export type AutocompleteOption = {
  value: string;
  /** 오른쪽에 흐리게 붙는 보조 정보. 학과면 단과대, 전공이면 소속 학부. */
  hint?: string;
};

type Props = {
  label: string;
  placeholder?: string;
  value: string;
  onChange: (value: string) => void;
  /** 이미 걸러진 후보. 부모가 API로 받아오거나 정적 목록을 넘긴다. */
  options: AutocompleteOption[];
  onSelect?: (option: AutocompleteOption) => void;
  required?: boolean;
  disabled?: boolean;
  /** 후보가 없을 때 보여줄 문구. 없으면 목록 자체를 띄우지 않는다. */
  emptyHint?: string;
  /**
   * 목록이 열리기 시작하는 최소 글자 수.
   *
   * 학과는 110개라 빈 칸에 포커스만 해도 목록이 쏟아지면 방해가 된다(기본 1).
   * 반대로 세부전공은 고른 학과에 딸린 두어 개뿐이라 바로 보여주는 게 낫다(0).
   */
  minChars?: number;
};

/**
 * 입력 아래로 후보가 펼쳐지는 자동완성.
 *
 * 자유 입력을 막지는 않는다 — DB에 아직 없는 학과를 쓰는 학생이 가입 자체를
 * 못 하면 안 되기 때문이다. 대신 정식 명칭을 눈에 띄게 놓아 그쪽을 고르게 한다.
 */
export function FieldAutocomplete({
  label,
  placeholder,
  value,
  onChange,
  options,
  onSelect,
  required,
  disabled,
  emptyHint,
  minChars = 1,
}: Props) {
  const [isOpen, setIsOpen] = useState(false);
  const [highlighted, setHighlighted] = useState(-1);
  const containerRef = useRef<HTMLDivElement>(null);
  const listId = useId();

  // 바깥을 누르면 닫는다. blur로 처리하면 후보를 클릭하는 순간 닫혀서 선택이 안 된다.
  useEffect(() => {
    function handlePointerDown(event: PointerEvent) {
      if (!containerRef.current?.contains(event.target as Node)) setIsOpen(false);
    }
    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, []);

  // 후보 목록이 바뀌면 하이라이트는 초기화한다.
  useEffect(() => setHighlighted(-1), [options]);

  function choose(option: AutocompleteOption) {
    onChange(option.value);
    onSelect?.(option);
    setIsOpen(false);
    setHighlighted(-1);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Escape") {
      setIsOpen(false);
      return;
    }
    if (!isOpen && (event.key === "ArrowDown" || event.key === "ArrowUp")) {
      setIsOpen(true);
      return;
    }
    if (options.length === 0) return;

    if (event.key === "ArrowDown") {
      event.preventDefault();
      setHighlighted((current) => (current + 1) % options.length);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setHighlighted((current) => (current <= 0 ? options.length - 1 : current - 1));
    } else if (event.key === "Enter" && highlighted >= 0) {
      // 후보를 고르는 중이라면 폼 제출로 이어지면 안 된다.
      event.preventDefault();
      choose(options[highlighted]);
    }
  }

  const hasEnoughInput = value.trim().length >= minChars;
  const showList = isOpen && hasEnoughInput && (options.length > 0 || Boolean(emptyHint));

  return (
    <div className="auth-autocomplete" ref={containerRef}>
      <label className="auth-field">
        <span>{label}</span>
        <input
          type="text"
          role="combobox"
          aria-expanded={showList}
          aria-controls={listId}
          aria-autocomplete="list"
          autoComplete="off"
          placeholder={placeholder}
          value={value}
          required={required}
          disabled={disabled}
          onChange={(event) => {
            onChange(event.target.value);
            setIsOpen(true);
          }}
          onFocus={() => setIsOpen(true)}
          onKeyDown={handleKeyDown}
        />
      </label>

      {showList ? (
        <ul className="auth-autocomplete-list" id={listId} role="listbox">
          {options.length === 0 ? (
            <li className="auth-autocomplete-empty">{emptyHint}</li>
          ) : (
            options.map((option, index) => (
              <li key={`${option.value}-${index}`}>
                <button
                  className={`auth-autocomplete-option${index === highlighted ? " is-active" : ""}`}
                  type="button"
                  role="option"
                  aria-selected={index === highlighted}
                  onMouseEnter={() => setHighlighted(index)}
                  onClick={() => choose(option)}
                >
                  <span>{option.value}</span>
                  {option.hint ? <small>{option.hint}</small> : null}
                </button>
              </li>
            ))
          )}
        </ul>
      ) : null}
    </div>
  );
}
