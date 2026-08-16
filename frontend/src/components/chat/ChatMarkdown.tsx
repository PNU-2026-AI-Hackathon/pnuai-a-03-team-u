import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * AI 챗 말풍선 본문. LLM 응답의 **굵게**·목록·표를 그대로 노출하지 않고
 * 렌더링한다. 로드맵 챗과 시간표 챗이 함께 쓴다.
 *
 * 링크는 새 탭으로 열고, 이미지 문법은 텍스트로 강등한다 — 챗 안에서 외부
 * 이미지를 불러올 이유가 없고, 프롬프트 인젝션으로 심긴 트래킹 픽셀을
 * 막는 의미도 있다.
 */
export function ChatMarkdown({ text }: { text: string }) {
  return (
    <div className="chat-md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ children, href }) => (
            <a href={href} target="_blank" rel="noreferrer noopener">{children}</a>
          ),
          img: ({ alt }) => <span>{alt ?? ""}</span>,
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}
