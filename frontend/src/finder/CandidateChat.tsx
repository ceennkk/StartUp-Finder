"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { useApi } from "./hooks";
import { useLanguage } from "./i18n";
import type { ChatCitation } from "./types";
import { ApiError } from "./api/client";

type Message = { id: number; role: "user" | "assistant"; text: string; citations?: ChatCitation[] };

export function CandidateChat({ candidateId }: { candidateId: string | null }) {
  const { api } = useApi();
  const { language, t } = useLanguage();
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [messages, busy]);

  async function ask(question: string) {
    const clean = question.trim();
    if (!clean || busy) return;
    const history = messages.slice(-8).map(({ role, text }) => ({ role, content: text }));
    setMessages((items) => [...items, { id: Date.now(), role: "user", text: clean }]);
    setInput("");
    setBusy(true);
    try {
      const response = await api.chat(clean, language, history, candidateId);
      setMessages((items) => [...items, { id: Date.now() + 1, role: "assistant", text: response.answer, citations: response.citations }]);
    } catch (error) {
      const detail = error instanceof ApiError && error.status >= 400
        ? error.message
        : t("chatError");
      setMessages((items) => [...items, { id: Date.now() + 1, role: "assistant", text: detail }]);
    } finally {
      setBusy(false);
    }
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void ask(input);
  }

  return <div className="fa-chat">
    {!open && <button className="fa-chat__launcher" onClick={() => setOpen(true)} aria-label={t("openChat")}>
      <span aria-hidden="true">✳</span>{t("ask")}
    </button>}
    {open && <section className="fa-chat__panel" role="dialog" aria-label={t("ask")}>
      <header className="fa-chat__head">
        <span className="fa-chat__mark" aria-hidden="true">✳</span>
        <div><b>{t("ask")}</b><small>{t("chatTechnical")}</small></div>
        <button onClick={() => setOpen(false)} aria-label={t("closeChat")}>×</button>
      </header>
      <div className="fa-chat__messages" aria-live="polite">
        {messages.length === 0 && <div className="fa-chat__welcome">
          <p>{t("askIntro")}</p>
          <div className="fa-chat__suggestions">
            {(["promptFunding", "promptScore", "promptTeam"] as const).map((key) =>
              <button key={key} onClick={() => void ask(t(key))}>{t(key)} <span aria-hidden="true">↗</span></button>,
            )}
          </div>
        </div>}
        {messages.map((message) => <article className={`fa-chat__message fa-chat__message--${message.role}`} key={message.id}>
          <p>{message.text}</p>
          {message.role === "assistant" && message.citations && message.citations.length > 0 && <div className="fa-chat__citations">
            <b>{t("sourcesUsed")}</b>
            {message.citations.map((citation) => <div className="fa-chat__citation" key={citation.id}>
              <strong>{citation.title}</strong><small>{citation.kind}</small>
              <q>{citation.quote}</q>
              {citation.url && <a href={citation.url} target="_blank" rel="noreferrer">{t("openOriginal")}</a>}
            </div>)}
          </div>}
          {message.role === "assistant" && message.citations?.length === 0 && <small className="fa-chat__no-citations">{t("noCitations")}</small>}
        </article>)}
        {busy && <div className="fa-chat__thinking"><span className="fa-chat__thinking-dot" />{t("thinking")}</div>}
        <div ref={endRef} />
      </div>
      <form className="fa-chat__form" onSubmit={submit}>
        <input value={input} onChange={(event) => setInput(event.target.value)} maxLength={1200} placeholder={t("chatPlaceholder")} aria-label={t("chatPlaceholder")} />
        <button type="submit" disabled={busy || !input.trim()} aria-label={t("send")}>↑</button>
      </form>
    </section>}
  </div>;
}
