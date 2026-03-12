from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components


def inject_responsive_styles() -> None:
    st.markdown(
        """
        <style>
        :root { font-size: clamp(13px, 0.55vw + 10px, 18px); }
        .block-container { padding-top: 0.65rem; padding-bottom: 1.1rem; }
        h1 { margin-top: 0.05rem !important; margin-bottom: 0.3rem !important; line-height: 1.08 !important; }
        div[class*="st-key-pogo_controls_bar"],
        .pogo-controls-bar-target {
          position: sticky !important;
          top: 2.8rem;
          z-index: 1150;
          padding: 0.36rem 0.48rem 0.54rem 0.48rem;
          border-radius: 0.7rem;
          border: 1px solid rgba(148, 163, 184, 0.22);
          background: rgba(15, 23, 42, 0.9);
          backdrop-filter: blur(8px);
          box-shadow: 0 10px 22px rgba(2, 8, 23, 0.32);
          transition: transform 0.32s cubic-bezier(0.22, 1, 0.36, 1), box-shadow 0.32s ease, opacity 0.32s ease, top 0.32s ease;
          opacity: 0.96;
        }
        div[class*="st-key-pogo_export_header_"] {
          max-width: 24rem;
          margin-left: auto;
          margin-right: auto;
        }
        body.pogo-controls-compact div[class*="st-key-pogo_controls_bar"],
        body.pogo-controls-compact .pogo-controls-bar-target {
          position: fixed !important;
          top: 2.1rem;
          left: 50%;
          width: min(76rem, calc(100vw - 1rem));
          padding-left: 0.78rem;
          padding-right: 0.78rem;
          transform: translateX(-50%) scale(0.965);
          transform-origin: top center;
          box-shadow: 0 8px 16px rgba(2, 8, 23, 0.28);
          z-index: 1300;
          pointer-events: auto;
        }
        body.pogo-controls-compact div[class*="st-key-pogo_controls_bar"] p,
        body.pogo-controls-compact .pogo-controls-bar-target p {
          font-size: 0.72rem !important;
          margin-bottom: 0.16rem;
        }
        body.pogo-controls-compact div[class*="st-key-pogo_controls_bar"] button,
        body.pogo-controls-compact .pogo-controls-bar-target button {
          min-height: 1.8rem !important;
          font-size: 0.8rem !important;
          padding-top: 0.1rem !important;
          padding-bottom: 0.1rem !important;
        }
        div[class*="st-key-pogo_ranking_table"] [data-testid="stDataFrame"] [role="columnheader"] {
          font-size: 0.78rem !important;
          white-space: nowrap !important;
        }
        div[class*="st-key-pogo_ranking_table"] [data-testid="stDataFrame"] [role="gridcell"] {
          font-size: 0.88rem !important;
        }
        /* Keep Current XP Ranking column widths stable across 7d/30d switches. */
        div[class*="st-key-pogo_ranking_table"] [data-testid="stDataFrame"] [role="columnheader"][aria-colindex="1"],
        div[class*="st-key-pogo_ranking_table"] [data-testid="stDataFrame"] [role="gridcell"][aria-colindex="1"] {
          width: 3.8rem !important;
          min-width: 3.8rem !important;
          max-width: 3.8rem !important;
        }
        div[class*="st-key-pogo_ranking_table"] [data-testid="stDataFrame"] [role="columnheader"][aria-colindex="2"],
        div[class*="st-key-pogo_ranking_table"] [data-testid="stDataFrame"] [role="gridcell"][aria-colindex="2"] {
          width: 9.4rem !important;
          min-width: 9.4rem !important;
          max-width: 9.4rem !important;
        }
        div[class*="st-key-pogo_ranking_table"] [data-testid="stDataFrame"] [role="columnheader"][aria-colindex="3"],
        div[class*="st-key-pogo_ranking_table"] [data-testid="stDataFrame"] [role="gridcell"][aria-colindex="3"] {
          width: 3.8rem !important;
          min-width: 3.8rem !important;
          max-width: 3.8rem !important;
        }
        div[class*="st-key-pogo_ranking_table"] [data-testid="stDataFrame"] [role="columnheader"][aria-colindex="4"],
        div[class*="st-key-pogo_ranking_table"] [data-testid="stDataFrame"] [role="gridcell"][aria-colindex="4"] {
          width: 8.8rem !important;
          min-width: 8.8rem !important;
          max-width: 8.8rem !important;
        }
        div[class*="st-key-pogo_ranking_table"] [data-testid="stDataFrame"] [role="columnheader"][aria-colindex="5"],
        div[class*="st-key-pogo_ranking_table"] [data-testid="stDataFrame"] [role="gridcell"][aria-colindex="5"] {
          width: 8.8rem !important;
          min-width: 8.8rem !important;
          max-width: 8.8rem !important;
        }
        div[class*="st-key-pogo_ranking_table"] [data-testid="stDataFrame"] [role="columnheader"][aria-colindex="6"],
        div[class*="st-key-pogo_ranking_table"] [data-testid="stDataFrame"] [role="gridcell"][aria-colindex="6"] {
          width: 7.6rem !important;
          min-width: 7.6rem !important;
          max-width: 7.6rem !important;
        }
        div[class*="st-key-pogo_ranking_table"] [data-testid="stDataFrame"] [role="columnheader"][aria-colindex="7"],
        div[class*="st-key-pogo_ranking_table"] [data-testid="stDataFrame"] [role="gridcell"][aria-colindex="7"] {
          width: 10.4rem !important;
          min-width: 10.4rem !important;
          max-width: 10.4rem !important;
        }
        div[class*="st-key-pogo_ranking_table"] [data-testid="stDataFrame"] [role="columnheader"][aria-colindex="8"],
        div[class*="st-key-pogo_ranking_table"] [data-testid="stDataFrame"] [role="gridcell"][aria-colindex="8"] {
          width: 8.6rem !important;
          min-width: 8.6rem !important;
          max-width: 8.6rem !important;
        }
        div[data-testid="stMetricLabel"] p,
        div[data-testid="stMetricDelta"] > div {
          white-space: normal !important;
          overflow-wrap: anywhere;
        }
        div[data-testid="stMetricValue"] > div {
          white-space: normal !important;
          overflow: visible !important;
          text-overflow: clip !important;
          overflow-wrap: anywhere;
          line-height: 1.02 !important;
          font-size: clamp(1.55rem, 1.9vw, 2.1rem) !important;
        }
        @media (max-width: 1200px) {
          .block-container { padding-left: 1rem; padding-right: 1rem; }
        }
        @media (max-width: 860px) {
          .block-container { padding-left: 0.65rem; padding-right: 0.65rem; }
          h1 { font-size: 1.45rem !important; }
          h2, h3 { font-size: 1.2rem !important; }
          div[class*="st-key-pogo_controls_bar"],
          .pogo-controls-bar-target { top: 2.2rem; }
          body.pogo-controls-compact div[class*="st-key-pogo_controls_bar"],
          body.pogo-controls-compact .pogo-controls-bar-target {
            top: 1.45rem;
            width: calc(100vw - 0.45rem);
            padding-left: 0.62rem;
            padding-right: 0.62rem;
            transform: translateX(-50%) scale(0.985);
          }
          div[class*="st-key-pogo_export_header_"] {
            max-width: none;
          }
          div[data-testid="stMetricValue"] > div {
            font-size: clamp(1.35rem, 6vw, 1.9rem) !important;
          }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    components.html(
        """
        <script>
        (() => {
          const parentWindow = window.parent;
          const parentDoc = parentWindow?.document;
          if (!parentWindow || !parentDoc) return;
          const className = "pogo-controls-compact";
          const barClass = "pogo-controls-bar-target";
          const threshold = 26;
          const normalize = (s) => String(s || "").replace(/\\s+/g, " ").trim().toLowerCase();
          const findRadioByLabel = (root, labels) => {
            const labelSet = new Set(labels.map((x) => normalize(x)));
            const radios = Array.from(root.querySelectorAll('div[data-testid="stRadio"]'));
            return radios.find((radio) => labelSet.has(normalize(radio.querySelector("label p")?.textContent))) || null;
          };
          const hasWindowControl = (root) => {
            const groups = Array.from(
              root.querySelectorAll('div[data-testid="stSegmentedControl"], div[data-baseweb="button-group"], div[role="radiogroup"]')
            );
            return groups.some((g) => {
              const labels = Array.from(g.querySelectorAll("button, label, p")).map((x) => normalize(x.textContent));
              return labels.includes("7d") && labels.includes("30d");
            });
          };
          const findControlsBarNode = () => {
            const keyed = parentDoc.querySelector('div[class*="st-key-pogo_controls_bar"]');
            if (keyed) return keyed;
            const pageRadio = findRadioByLabel(parentDoc, ["Page"]);
            if (!pageRadio) return null;
            const candidates = [];
            let node = pageRadio;
            while (node) {
              if (node.matches('div[data-testid="stVerticalBlock"], div[data-testid="stElementContainer"]')) {
                candidates.push(node);
              }
              node = node.parentElement;
            }
            for (const candidate of candidates) {
              if (findRadioByLabel(candidate, ["Global Group", "Personal Group", "Group"]) || hasWindowControl(candidate)) {
                return candidate;
              }
            }
            return pageRadio.closest('div[data-testid="stElementContainer"]') || candidates[0] || null;
          };
          const bindControlsBarClass = () => {
            parentDoc.querySelectorAll(`.${barClass}`).forEach((el) => el.classList.remove(barClass));
            const target = findControlsBarNode();
            if (target) target.classList.add(barClass);
          };
          const scrollHostCandidates = () => {
            const nodes = [
              parentDoc.querySelector('section.main'),
              parentDoc.querySelector('[data-testid="stAppViewContainer"]'),
              parentDoc.querySelector('[data-testid="stMain"]'),
              parentDoc.scrollingElement,
              parentDoc.documentElement,
              parentDoc.body,
            ];
            return nodes.filter(Boolean);
          };
          const getScrollY = () => {
            const tops = scrollHostCandidates().map((n) => Number(n?.scrollTop || 0));
            tops.push(Number(parentWindow.scrollY || 0));
            tops.push(Number(parentWindow.pageYOffset || 0));
            return Math.max(0, ...tops);
          };
          const applyCompactClass = () => {
            bindControlsBarClass();
            const compact = getScrollY() > threshold;
            parentDoc.body.classList.toggle(className, compact);
          };
          let scrollRaf = 0;
          const onScroll = () => {
            if (scrollRaf) return;
            scrollRaf = parentWindow.requestAnimationFrame(() => {
              scrollRaf = 0;
              applyCompactClass();
            });
          };
          const onResize = () => applyCompactClass();
          if (!parentWindow.__pogoCompactWindowListenerInstalled) {
            scrollHostCandidates().forEach((host) => {
              if (host && host.addEventListener) {
                host.addEventListener("scroll", onScroll, { passive: true });
              }
            });
            parentWindow.addEventListener("scroll", onScroll, { passive: true });
            parentDoc.addEventListener("scroll", onScroll, { passive: true, capture: true });
            parentWindow.addEventListener("resize", onResize, { passive: true });
            parentWindow.__pogoCompactWindowListenerInstalled = true;
          }
          if (!parentWindow.__pogoCompactWindowObserverInstalled) {
            const observer = new MutationObserver(() => applyCompactClass());
            observer.observe(parentDoc.body, { childList: true, subtree: true });
            parentWindow.__pogoCompactWindowObserverInstalled = true;
          }
          parentWindow.setTimeout(applyCompactClass, 120);
          applyCompactClass();
        })();
        </script>
        """,
        height=1,
        width=1,
    )
