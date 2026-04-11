import { useOrbiStore } from "@/stores/orbiStore";
import { useActivityStore } from "@/stores/activityStore";
import { useThreadStore } from "@/stores/threadStore";
import { useCallback, useEffect, useRef } from "react";
import { useLocation } from "react-router-dom";
import OrbiDog from "./OrbiDog";

const IDLE_TIMEOUT_MS = 5 * 60 * 1000;

export default function Orbi() {
  const visible = useOrbiStore((s) => s.visible);
  const state = useOrbiStore((s) => s.state);
  const orbiName = useOrbiStore((s) => s.name);
  const setState = useOrbiStore((s) => s.setState);
  const setBaseState = useOrbiStore((s) => s.setBaseState);
  const flashHappy = useOrbiStore((s) => s.flashHappy);
  const revertToBase = useOrbiStore((s) => s.revertToBase);

  const mainStreaming = useActivityStore((s) => s.isStreaming);
  const threadStreaming = useThreadStore((s) => s.isStreaming);
  const isStreaming = mainStreaming || threadStreaming;
  const location = useLocation();

  const idleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const typingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const TEXT_TYPES = new Set(["text", "search", "email", "password", "url", "tel", ""]);
    function onInput(e: Event) {
      const el = e.target as HTMLElement;
      const tag = el.tagName;
      if (tag === "INPUT") {
        if (!TEXT_TYPES.has((el as HTMLInputElement).type)) return;
      } else if (tag !== "TEXTAREA") {
        return;
      }
      const s = useOrbiStore.getState().state;
      if (s === "thinking" || s === "happy" || s === "error") return;
      setState("typing");
      if (typingTimerRef.current) clearTimeout(typingTimerRef.current);
      typingTimerRef.current = setTimeout(() => {
        if (useOrbiStore.getState().state === "typing") {
          revertToBase();
        }
      }, 700);
    }
    document.addEventListener("input", onInput, { passive: true });
    return () => {
      document.removeEventListener("input", onInput);
      if (typingTimerRef.current) clearTimeout(typingTimerRef.current);
    };
  }, [setState, revertToBase]);

  useEffect(() => {
    if (isStreaming) {
      setState("thinking");
    } else {
      const cur = useOrbiStore.getState().state;
      if (cur === "thinking") {
        flashHappy();
      }
    }
  }, [isStreaming]); // eslint-disable-line react-hooks/exhaustive-deps

  const isSession = location.pathname.includes("/sessions/");
  useEffect(() => {
    setBaseState(isSession ? "reading" : "idle");
  }, [isSession, setBaseState]);

  const resetIdleTimer = useCallback(() => {
    if (state === "sleeping") {
      setBaseState(isSession ? "reading" : "idle");
    }
    if (idleTimerRef.current) clearTimeout(idleTimerRef.current);
    idleTimerRef.current = setTimeout(() => {
      const { state: s } = useOrbiStore.getState();
      if (s === "idle" || s === "reading") {
        setBaseState("sleeping");
      }
    }, IDLE_TIMEOUT_MS);
  }, [setBaseState, state, isSession]);

  useEffect(() => {
    const events = ["mousemove", "keydown", "click", "scroll"] as const;
    const handler = () => resetIdleTimer();
    events.forEach((e) => window.addEventListener(e, handler, { passive: true }));
    resetIdleTimer();
    return () => {
      events.forEach((e) => window.removeEventListener(e, handler));
      if (idleTimerRef.current) clearTimeout(idleTimerRef.current);
    };
  }, [resetIdleTimer]);

  if (!visible) return null;

  return (
    <div className="relative flex items-center">
      <div
        className="group relative flex items-center rounded-lg px-1 py-0.5"
        aria-label={`${orbiName} assistant`}
        title={orbiName}
      >
        <OrbiDog state={state} size={46} />
      </div>
    </div>
  );
}
