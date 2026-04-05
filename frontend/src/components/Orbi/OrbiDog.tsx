import "./orbi-dog.css";

export type OrbiState =
  | "idle"
  | "thinking"
  | "happy"
  | "error"
  | "sleeping"
  | "typing"
  | "reading";

interface OrbiDogProps {
  state: OrbiState;
  size?: number;
  className?: string;
}

export default function OrbiDog({
  state,
  size = 44,
  className = "",
}: OrbiDogProps) {
  const w = Math.round(size * 1.4);

  return (
    <div
      className={`orbi-dog orbi-dog--${state} ${className}`}
      style={{ width: w, height: size }}
    >
      {/* Dog — ported from harshalparmar/husky */}
      <div className="husky">
        <div className="mane">
          <div className="coat" />
        </div>
        <div className="body">
          <div className="head">
            <div className="ear" />
            <div className="ear" />
            <div className="face">
              <div className="eye" />
              <div className="eye" />
              <div className="nose" />
              <div className="mouth">
                <div className="lips" />
                <div className="tongue" />
              </div>
            </div>
          </div>
          <div className="torso" />
        </div>
        <div className="legs">
          <div className="front-legs">
            <div className="leg" />
            <div className="leg" />
          </div>
          <div className="hind-leg" />
        </div>
        <div className="tail">
          <div className="tail">
            <div className="tail">
              <div className="tail">
                <div className="tail">
                  <div className="tail">
                    <div className="tail" />
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* State icons */}
      {state === "typing" && (
        <span className="orbi-state-icon orbi-state-icon--typing">⌨️</span>
      )}
      {state === "thinking" && (
        <span className="orbi-state-icon orbi-state-icon--thinking">🤔</span>
      )}
      {state === "error" && (
        <span className="orbi-state-icon orbi-state-icon--error">😢</span>
      )}

      {/* Effects overlay */}
      <svg className="orbi-fx-layer" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg" overflow="visible">
        <g className="orbi-fx orbi-fx--zzz">
          <text className="orbi-z orbi-z--1" x="80" y="8" fontSize="11" fontWeight="bold" fill="#9CA3AF" fontFamily="serif">Z</text>
          <text className="orbi-z orbi-z--2" x="87" y="0" fontSize="8" fontWeight="bold" fill="#9CA3AF" fontFamily="serif">z</text>
          <text className="orbi-z orbi-z--3" x="92" y="-6" fontSize="5.5" fontWeight="bold" fill="#9CA3AF" fontFamily="serif">z</text>
        </g>
        <g className="orbi-fx orbi-fx--sparkles">
          <path className="orbi-star orbi-star--1" d="M5,30 L7,24 L9,30 L15,32 L9,34 L7,40 L5,34 L-1,32 Z" fill="#FFD700" />
          <path className="orbi-star orbi-star--2" d="M88,2 L89.5,-2 L91,2 L95,3.5 L91,5 L89.5,9 L88,5 L84,3.5 Z" fill="#FFC107" />
          <path className="orbi-star orbi-star--3" d="M94,20 L95,18 L96,20 L98,21 L96,22 L95,24 L94,22 L92,21 Z" fill="#FFB300" />
        </g>
      </svg>
    </div>
  );
}
