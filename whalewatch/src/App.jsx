import React from "react";

export default function WhaleWatch() {
  return React.createElement("div", {
    style: { background: "#06090e", color: "#00ff9d", fontFamily: "'IBM Plex Mono', monospace",
             height: "100vh", display: "flex", alignItems: "center", justifyContent: "center",
             flexDirection: "column", gap: 16 }
  },
    React.createElement("h1", {style:{fontSize:48}}, "\uD83D\uDC0B WHALEWATCH"),
    React.createElement("p", { style: { color: "#9ca8b7", fontSize: 16 } }, "Infrastructure test — React renders OK"),
    React.createElement("p", { style: { color: "#3e4a5a", fontSize: 12 } },
      "React: OK | Vite: OK | Deploy: OK | Time: " + new Date().toISOString()),
    React.createElement("div", {style:{marginTop:20,display:"flex",gap:12}},
      React.createElement("a", {href:"/", style:{color:"#00ff9d",fontSize:12}}, "Home"),
      React.createElement("a", {href:"/dashboard", style:{color:"#00ff9d",fontSize:12}}, "Dashboard"),
      React.createElement("a", {href:"/learn", style:{color:"#00ff9d",fontSize:12}}, "Learn")
    )
  );
}
