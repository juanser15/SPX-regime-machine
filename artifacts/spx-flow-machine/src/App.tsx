import { useEffect, useState } from "react";

export default function App() {
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const check = async () => {
      try {
        const res = await fetch("/_stcore/health");
        if (res.ok) {
          setReady(true);
          return;
        }
      } catch {}
      setTimeout(check, 1000);
    };
    check();
  }, []);

  return (
    <div
      style={{
        width: "100vw",
        height: "100vh",
        margin: 0,
        padding: 0,
        overflow: "hidden",
        background: "#0e1117",
      }}
    >
      {!ready && (
        <div
          style={{
            position: "absolute",
            inset: 0,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            color: "#fff",
            fontFamily: "sans-serif",
            gap: "16px",
          }}
        >
          <div style={{ fontSize: "36px" }}>📈</div>
          <div style={{ fontSize: "20px", fontWeight: 700 }}>
            SPX Flow Machine
          </div>
          <div style={{ fontSize: "13px", color: "#aaa" }}>
            Starting dashboard…
          </div>
          <div
            style={{
              width: "200px",
              height: "4px",
              background: "#333",
              borderRadius: "2px",
              overflow: "hidden",
            }}
          >
            <div
              style={{
                height: "100%",
                width: "40%",
                background: "#4CAF50",
                borderRadius: "2px",
                animation: "slide 1.5s ease-in-out infinite",
              }}
            />
          </div>
          <style>{`@keyframes slide { 0%{transform:translateX(-100%)} 100%{transform:translateX(400%)} }`}</style>
        </div>
      )}
      <iframe
        src="/st/"
        style={{
          width: "100%",
          height: "100%",
          border: "none",
          opacity: ready ? 1 : 0,
          transition: "opacity 0.5s ease",
        }}
        title="SPX Flow Machine"
        allow="fullscreen"
      />
    </div>
  );
}
