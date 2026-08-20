import { useEffect, useRef } from "react";

export default function ConversationPanel({ conversation = [] }) {
  const bottomRef = useRef(null);
  const isEmpty = conversation.length === 0;

  useEffect(() => {
    if (!isEmpty) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [conversation, isEmpty]);

  return (
    <div className="chat-panel">
      {/* Background Glows */}
      <div className="glow-blue"></div>
      <div className="glow-pink"></div>

      {/* EMPTY STATE */}
      {isEmpty ? (
        <div className="chat-empty">
          <div className="sparkle">
            <svg viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg">
              {/* Star 1 - Main (Top Right-ish) */}
              <path d="M22 4L24.5 13.5L34 16L24.5 18.5L22 28L19.5 18.5L10 16L19.5 13.5L22 4Z" fill="currentColor" />
              {/* Star 2 - Side (Middle Left) */}
              <path d="M10 18L11.5 24L17.5 25.5L11.5 27L10 33L8.5 27L2.5 25.5L8.5 24L10 18Z" fill="currentColor" fillOpacity="0.7" />
              {/* Star 3 - Bottom (Small) */}
              <path d="M26 26L27 30L31 31L27 32L26 36L25 32L21 31L25 30L26 26Z" fill="currentColor" fillOpacity="0.5" />
            </svg>
          </div>
          <p>Ask anything to Neura</p>
        </div>
      ) : (
        <div className="messages-container">
          {conversation.map((msg, index) => (
            <div key={index} className={`chat-row ${msg.role}`}>

              <span className="chat-label">
                {msg.role === "user" ? "You" : "Neura"}
              </span>

              <div className={`chat-bubble ${msg.role}`}>
                {msg.content}
              </div>

            </div>
          ))}

          <div ref={bottomRef} />
        </div>
      )}

    </div>
  );
}