"use client";

import { useEffect, useRef, type CSSProperties, type ReactNode } from "react";
import { useLanguage, type TranslationKey } from "./i18n";

/** Adds .is-in to every [data-reveal] once it scrolls into view. Calm, one-shot. */
function useReveal() {
  const root = useRef<HTMLElement>(null);
  useEffect(() => {
    const nodes = root.current?.querySelectorAll<HTMLElement>("[data-reveal]") ?? [];
    if (!("IntersectionObserver" in window)) {
      nodes.forEach((n) => n.classList.add("is-in"));
      return;
    }
    const io = new IntersectionObserver((entries) => {
      entries.forEach((e) => {
        if (e.isIntersecting) {
          e.target.classList.add("is-in");
          io.unobserve(e.target);
        }
      });
    }, { threshold: 0.12 });
    nodes.forEach((n) => io.observe(n));
    return () => io.disconnect();
  }, []);
  return root;
}

function Scene({ n, title, text, children, flip = false }: { n: string; title: string; text: string; children: ReactNode; flip?: boolean }) {
  return <section className={`hx-scene${flip ? " is-flip" : ""}`} data-reveal>
    <div className="hx-scene__copy">
      <span className="hx-scene__n">{n}</span>
      <h2>{title}</h2>
      <p>{text}</p>
    </div>
    <div className="hx-scene__visual">{children}</div>
  </section>;
}

const SOURCES = ["arXiv", "OpenAlex", "GitHub", "Hugging Face", "EXIST", "CORDIS", "Uni-Feeds", "Team-Import"];
const RECORDS: { key: TranslationKey; keep: boolean }[] = [
  { key: "hxRec1", keep: true },
  { key: "hxRec2", keep: false },
  { key: "hxRec3", keep: true },
  { key: "hxRec4", keep: false },
  { key: "hxRec5", keep: true },
  { key: "hxRec6", keep: false },
];
const CRITERIA: { key: TranslationKey; rating: TranslationKey; value: number }[] = [
  { key: "hxCrit1", rating: "hxStrong", value: 100 },
  { key: "hxCrit2", rating: "hxStrong", value: 100 },
  { key: "hxCrit3", rating: "hxModerate", value: 67 },
  { key: "hxCrit4", rating: "hxOpen", value: 0 },
];

export function PipelinePage() {
  const { t } = useLanguage();
  const root = useReveal();

  return <article className="hx" ref={root} aria-labelledby="pipeline-title">
    <header className="hx-hero" data-reveal>
      <div className="hx-hero__glow" aria-hidden="true" />
      <p className="hx-kicker">{t("howItWorks")}</p>
      <h1 id="pipeline-title">{t("pipelineTitleA")}<br /><em>{t("pipelineTitleB")}</em></h1>
      <p className="hx-lead">{t("pipelineLead")}</p>
      <span className="hx-hero__scroll" aria-hidden="true">↓</span>
    </header>

    <Scene n="01" title={t("hiwS1T")} text={t("hiwS1D")}>
      <div className="hx-collect" aria-hidden="true">
        {SOURCES.map((s, i) => <span key={s} style={{ "--i": i } as CSSProperties}>{s}</span>)}
        <i className="hx-collect__core" />
      </div>
    </Scene>

    <Scene n="02" title={t("hiwS2T")} text={t("hiwS2D")} flip>
      <ul className="hx-select" aria-hidden="true">
        {RECORDS.map((r, i) => <li key={r.key} className={r.keep ? "is-keep" : ""} style={{ "--i": i } as CSSProperties}>
          <span>{t(r.key)}</span><b>{r.keep ? t("hxRelevant") : t("hxIgnored")}</b>
        </li>)}
      </ul>
    </Scene>

    <Scene n="03" title={t("hiwS3T")} text={t("hiwS3D")}>
      <div className="hx-graph" aria-hidden="true">
        <svg viewBox="0 0 600 360" preserveAspectRatio="none">
          <path className="hx-graph__edge" d="M120 90 C 260 90, 260 180, 300 180" />
          <path className="hx-graph__edge" d="M300 180 C 340 180, 340 270, 480 270" />
        </svg>
        <span className="hx-graph__node" style={{ left: "20%", top: "25%" }}><small>{t("graphPersonType")}</small>{t("hxPerson")}</span>
        <span className="hx-graph__node is-venture" style={{ left: "50%", top: "50%" }}><small>{t("graphVentureType")}</small>{t("graphVenture")}</span>
        <span className="hx-graph__node" style={{ left: "80%", top: "75%" }}><small>{t("hxProgramType")}</small>{t("hxProgram")}</span>
        <em className="hx-graph__rel" style={{ left: "27%", top: "45%" }}>{t("hxEdgeFounded")}</em>
        <em className="hx-graph__rel" style={{ left: "74%", top: "58%" }}>{t("hxEdgeSelected")}</em>
        <blockquote className="hx-graph__quote">{t("hiwExampleQuote")}<cite>{t("hiwExampleSource")}</cite></blockquote>
      </div>
    </Scene>

    <Scene n="04" title={t("hiwS4T")} text={t("hiwS4D")} flip>
      <div className="hx-rank" aria-hidden="true">
        <div className="hx-rank__score"><b>{t("graphVenture")}</b><strong>89</strong><small>/100</small></div>
        <ul>
          {CRITERIA.map((c, i) => <li key={c.key} style={{ "--i": i, "--v": c.value } as CSSProperties}>
            <span>{t(c.key)}</span><i><u /></i><b>{t(c.rating)}</b>
          </li>)}
        </ul>
        <p className="hx-rank__note">{t("hiwExampleLabel")}</p>
      </div>
    </Scene>

    <section className="hx-tech" aria-labelledby="tx-title">
      <header className="hx-tech__intro" data-reveal>
        <p className="hx-kicker">{t("txKicker")}</p>
        <h2 id="tx-title">{t("txTitle")}<br /><em>{t("txTitleB")}</em></h2>
        <p className="hx-lead">{t("txLead")}</p>
      </header>

      <div className="hx-tech__scene" data-reveal>
        <div className="hx-tech__copy">
          <span className="hx-scene__n">{t("txD1N")}</span>
          <h3>{t("txD1T")}<br /><em>{t("txD1TB")}</em></h3>
          <p>{t("txD1D")}</p>
        </div>
        <div className="hx-tech__panel hx-decide" aria-hidden="true">
          <span className="hx-tech__tag">{t("hiwExampleLabel")}</span>
          <div className="hx-decide__in"><small>{t("txD1In")}</small><i /><i /><i /><i /></div>
          <span className="hx-decide__wire" />
          <div className="hx-decide__model"><small>OpenAI</small>Decisions API</div>
          <span className="hx-decide__wire" />
          <pre className="hx-decide__out">{`{
  "choice": "${t("txD1Choice")}",
  "confidence": 0.94,
  "reason": "${t("txD1Reason")}"
}`}</pre>
          <p className="hx-tech__note">{t("txD1Note")}</p>
        </div>
      </div>

      <div className="hx-tech__scene is-flip" data-reveal>
        <div className="hx-tech__copy">
          <span className="hx-scene__n">{t("txT1N")}</span>
          <h3>{t("txT1T")}<br /><em>{t("txT1TB")}</em></h3>
          <p>{t("txT1D")}</p>
        </div>
        <div className="hx-tech__panel hx-time" aria-hidden="true">
          <span className="hx-tech__tag">{t("hiwExampleLabel")}</span>
          <div className="hx-time__who">{t("hxPerson")}</div>
          <ul>
            <li style={{ "--from": 0, "--to": 62, "--i": 0 } as CSSProperties} className="is-closed">
              <span>{t("txT1F1")}</span><i><u /></i><b>2021 → 2024 · {t("txT1Closed")}</b>
            </li>
            <li style={{ "--from": 62, "--to": 100, "--i": 1 } as CSSProperties}>
              <span>{t("txT1F2")}</span><i><u /></i><b>2024 → · {t("txT1Open")}</b>
            </li>
            <li style={{ "--from": 82, "--to": 100, "--i": 2 } as CSSProperties}>
              <span>{t("txT1F3")}</span><i><u /></i><b>2025 → · {t("txT1Open")}</b>
            </li>
          </ul>
          <div className="hx-time__axis"><span>2021</span><span>2022</span><span>2023</span><span>2024</span><span>2025</span><span>2026</span></div>
          <p className="hx-tech__note">{t("txT1Ep")}</p>
        </div>
      </div>

      <div className="hx-tech__scene" data-reveal>
        <div className="hx-tech__copy">
          <span className="hx-scene__n">{t("txS1N")}</span>
          <h3>{t("txS1T")}<br /><em>{t("txS1TB")}</em></h3>
          <p>{t("txS1D")}</p>
        </div>
        <div className="hx-tech__panel hx-formula" aria-hidden="true">
          <div className="hx-formula__map">
            <span><b>{t("hxStrong")}</b>100</span>
            <span><b>{t("hxModerate")}</b>67</span>
            <span><b>{t("hxWeak")}</b>33</span>
          </div>
          <div className="hx-formula__eq">
            <span>(100 + 100 + 67)</span><i>÷</i><span>3</span><i>=</i><strong>89</strong>
          </div>
          <p className="hx-tech__note">{t("txS1Rule")}</p>
        </div>
      </div>

      <div className="hx-stack" data-reveal>
        <p className="hx-kicker">{t("txStackTitle")}</p>
        <ul>
          <li><b>Neon · PostgreSQL</b><span>{t("txStack1")}</span></li>
          <li><b>OpenAI Decisions</b><span>{t("txStack2")}</span></li>
          <li><b>GPT-6 Luna</b><span>{t("txStack3")}</span></li>
          <li><b>Graphiti</b><span>{t("txStack4")}</span></li>
          <li><b>Neo4j</b><span>{t("txStack5")}</span></li>
        </ul>
      </div>
    </section>

    <footer className="hx-end" data-reveal>
      <div className="hx-end__glow" aria-hidden="true" />
      <h2>{t("hxCtaTitle")}<br /><em>{t("hxCtaTitleB")}</em></h2>
      <p>{t("pipelineFooter")}</p>
      <a className="hx-end__cta" href="#/entdecken">{t("homeDiscoverAction")}</a>
    </footer>
  </article>;
}
