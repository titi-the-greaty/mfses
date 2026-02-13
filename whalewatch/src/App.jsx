import React from "react";
import { useState, useEffect, useRef, useMemo, useContext, useCallback } from "react";
import * as THREE from "three";
import { AreaChart, Area, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Treemap, ScatterChart, Scatter, ZAxis, ComposedChart, Line } from "recharts";
import { useWhaleWatchData } from './api/index.js';

/*  THEMES  */
var dark = {
  bg:"#06090e",bgPanel:"#0c1018",bgAlt:"#111822",bgWin:"#0a0f16",
  border:"#1a3328",borderBright:"#00ff9d",text:"#9ca8b7",textBright:"#e2e8f0",
  accent:"#00ff9d",accentDim:"#00b371",sell:"#ff3366",buy:"#00ff9d",warn:"#ffc940",
  muted:"#3e4a5a",highlight:"#00ff9d10",inputBg:"#080c12",scrollbar:"#1a3328",
  h5:"#00ff9d",h4:"#33cc5a",h3:"#228b3b",h2:"#1a4a2a",
  n5:"#ff3366",n4:"#cc3358",n3:"#8b2240",n2:"#4a1a28"
};
var light = {
  bg:"#eef1f5",bgPanel:"#ffffff",bgAlt:"#e4e8ee",bgWin:"#f7f9fb",
  border:"#3a8a5e",borderBright:"#0d7a42",text:"#2a3040",textBright:"#0a0e14",
  accent:"#0d7a42",accentDim:"#0a5e34",sell:"#cc1144",buy:"#0d7a42",warn:"#b38f00",
  muted:"#8090a4",highlight:"#0d7a4210",inputBg:"#f0f3f7",scrollbar:"#3a8a5e",
  h5:"#0d7a42",h4:"#2a9a48",h3:"#5ab870",h2:"#a0d4aa",
  n5:"#cc1144",n4:"#b83355",n3:"#cc6680",n2:"#e0a0b0"
};
var themes = { dark: dark, light: light };

/*  DATA CONTEXT  */
var DataContext = React.createContext(null);

/*  MOCK DATA (fallbacks)  */
var TRADES = [
  {id:1,insider:"Jensen Huang",title:"CEO",company:"NVIDIA",ticker:"NVDA",type:"SELL",shares:120000,value:17100000,date:"2026-02-12",cap:3480e9,flagged:false,reason:""},
  {id:2,insider:"Mark Zuckerberg",title:"CEO",company:"Meta",ticker:"META",type:"SELL",shares:200000,value:124260000,date:"2026-02-11",cap:1580e9,flagged:false,reason:""},
  {id:3,insider:"Lisa Su",title:"CEO",company:"AMD",ticker:"AMD",type:"BUY",shares:50000,value:5410000,date:"2026-02-11",cap:175e9,flagged:true,reason:"BUY after -31% in 90d"},
  {id:4,insider:"Jamie Dimon",title:"CEO",company:"JPMorgan",ticker:"JPM",type:"BUY",shares:25000,value:6215000,date:"2026-02-10",cap:710e9,flagged:false,reason:""},
  {id:5,insider:"Tim Cook",title:"CEO",company:"Apple",ticker:"AAPL",type:"SELL",shares:300000,value:69840000,date:"2026-02-10",cap:3620e9,flagged:false,reason:""},
  {id:6,insider:"Cathie Wood",title:"CEO",company:"ARK Invest",ticker:"ARKK",type:"BUY",shares:450000,value:23580000,date:"2026-02-09",cap:8.2e9,flagged:true,reason:"BUY after -28% sector drop"},
  {id:7,insider:"Satya Nadella",title:"CEO",company:"Microsoft",ticker:"MSFT",type:"SELL",shares:80000,value:34568000,date:"2026-02-09",cap:3210e9,flagged:false,reason:""},
  {id:8,insider:"Andy Jassy",title:"CEO",company:"Amazon",ticker:"AMZN",type:"SELL",shares:150000,value:32760000,date:"2026-02-08",cap:2280e9,flagged:false,reason:""},
  {id:9,insider:"Mary Barra",title:"CEO",company:"GM",ticker:"GM",type:"BUY",shares:100000,value:4820000,date:"2026-02-08",cap:54e9,flagged:true,reason:"BUY after -33% in 60d"},
  {id:10,insider:"Pat Gelsinger",title:"Fmr CEO",company:"Intel",ticker:"INTC",type:"SELL",shares:75000,value:1672500,date:"2026-02-07",cap:95e9,flagged:false,reason:""},
  {id:11,insider:"Elon Musk",title:"CEO",company:"Tesla",ticker:"TSLA",type:"SELL",shares:500000,value:191300000,date:"2026-02-07",cap:1220e9,flagged:false,reason:""},
  {id:12,insider:"Brian Moynihan",title:"CEO",company:"BofA",ticker:"BAC",type:"BUY",shares:60000,value:2508000,date:"2026-02-06",cap:328e9,flagged:true,reason:"Cluster buy: 3 insiders in 7d"}
];

var CANDLE = [];
for (var i = 0; i < 60; i++) {
  var b = 140 + Math.sin(i/8)*20 + i*0.3;
  var o = b + (Math.random()-0.5)*6;
  var c = b + (Math.random()-0.5)*6;
  var dd = new Date(2026, 0, i+1);
  CANDLE.push({
    date: (dd.getMonth()+1)+"/"+dd.getDate(),
    open: +o.toFixed(2), close: +c.toFixed(2),
    high: +(Math.max(o,c)+Math.random()*4).toFixed(2),
    low: +(Math.min(o,c)-Math.random()*4).toFixed(2),
    volume: Math.floor(2e7+Math.random()*4e7)
  });
}

var QUANT = [];
for (var qi = 0; qi < 30; qi++) {
  QUANT.push({day:qi+1,alpha:+(Math.sin(qi/4)*2.5+Math.random()*1.2).toFixed(2),sharpe:+(1.2+Math.cos(qi/5)*0.6+Math.random()*0.3).toFixed(2),vol:+(15+Math.sin(qi/3)*5+Math.random()*3).toFixed(2)});
}

var SECTORS = [
  {sector:"Technology",change:2.4,mcap:"$14.2T",tickers:[{t:"AAPL",c:1.2},{t:"MSFT",c:0.8},{t:"NVDA",c:4.6},{t:"GOOG",c:1.1},{t:"META",c:-0.3},{t:"AVGO",c:3.2},{t:"AMD",c:-2.8},{t:"INTC",c:-1.4},{t:"CRM",c:0.6},{t:"ORCL",c:1.8}]},
  {sector:"Financials",change:0.8,mcap:"$9.1T",tickers:[{t:"JPM",c:1.4},{t:"BAC",c:0.3},{t:"WFC",c:-0.2},{t:"GS",c:2.1},{t:"MS",c:1.6},{t:"V",c:0.4},{t:"AXP",c:1.1}]},
  {sector:"Healthcare",change:-0.6,mcap:"$6.8T",tickers:[{t:"UNH",c:-1.2},{t:"JNJ",c:0.3},{t:"LLY",c:2.8},{t:"PFE",c:-2.1},{t:"ABBV",c:0.7},{t:"MRK",c:-0.4}]},
  {sector:"Energy",change:1.6,mcap:"$3.2T",tickers:[{t:"XOM",c:2.3},{t:"CVX",c:1.8},{t:"COP",c:3.1},{t:"SLB",c:0.9},{t:"EOG",c:2.4},{t:"OXY",c:-0.6}]},
  {sector:"Consumer",change:-0.3,mcap:"$7.5T",tickers:[{t:"AMZN",c:0.6},{t:"TSLA",c:-3.2},{t:"HD",c:0.4},{t:"NKE",c:-1.8},{t:"MCD",c:0.2},{t:"COST",c:1.3}]},
  {sector:"Industrials",change:0.4,mcap:"$4.1T",tickers:[{t:"GE",c:1.5},{t:"CAT",c:2.0},{t:"RTX",c:0.3},{t:"HON",c:0.8},{t:"BA",c:-1.4}]},
  {sector:"Real Estate",change:-1.2,mcap:"$1.4T",tickers:[{t:"PLD",c:-0.8},{t:"AMT",c:-1.5},{t:"EQIX",c:0.3},{t:"SPG",c:-2.0}]},
  {sector:"Utilities",change:0.2,mcap:"$1.6T",tickers:[{t:"NEE",c:0.4},{t:"DUK",c:0.1},{t:"SO",c:-0.3},{t:"AEP",c:0.6}]}
];

var BOARD = [
  {id:"aapl",name:"Apple Inc",type:"co",x:50,y:50,conn:null,role:null,sh:null},
  {id:"tc",name:"Tim Cook",type:"p",x:20,y:20,conn:["aapl","nike"],role:"CEO",sh:"3.28M"},
  {id:"ag",name:"Al Gore",type:"p",x:80,y:25,conn:["aapl","gen"],role:"Board",sh:"980K"},
  {id:"jw",name:"J. Williams",type:"p",x:15,y:75,conn:["aapl"],role:"COO",sh:"1.12M"},
  {id:"aj",name:"A. Jung",type:"p",x:75,y:80,conn:["aapl","unl"],role:"Board",sh:"410K"},
  {id:"nike",name:"Nike Inc",type:"co",x:10,y:5,conn:null,role:null,sh:null},
  {id:"gen",name:"Generation IM",type:"co",x:90,y:10,conn:null,role:null,sh:null},
  {id:"unl",name:"Unilever",type:"co",x:90,y:90,conn:null,role:null,sh:null}
];

var BTREE = [
  {name:"Assets $352B",size:352,fill:"#00ff9d"},{name:"Cash $29B",size:29,fill:"#00cc7a"},
  {name:"Securities $31B",size:31,fill:"#00b36b"},{name:"Receivables $60B",size:60,fill:"#009959"},
  {name:"PPE $43B",size:43,fill:"#007744"},{name:"Liabilities $290B",size:290,fill:"#ff3366"},
  {name:"Debt $111B",size:111,fill:"#cc2952"},{name:"Payables $69B",size:69,fill:"#b3243f"},
  {name:"Equity $62B",size:62,fill:"#ffc940"},{name:"Retained $4B",size:4,fill:"#e6b800"}
];

var AIR = {
  def:"WhaleWatch AI ready. Try: 'flagged', 'top sells', 'NVDA', 'sector', 'help'.",
  flag:"\u2b2c 4 FLAGGED TRADES:\n  Lisa Su (AMD) BUY $5.4M after -31%\n  Cathie Wood (ARKK) BUY $23.6M\n  Mary Barra (GM) BUY $4.8M after -33%\n  Brian Moynihan (BAC) cluster buy",
  sell:"\u2b2c TOP SELLS (7d):\n  1. Musk TSLA $191.3M\n  2. Zuckerberg META $124.3M\n  3. Cook AAPL $69.8M\n  4. Nadella MSFT $34.6M\n  5. Jassy AMZN $32.8M",
  nvda:"\u2b2c NVDA: Huang sold 120K ($17.1M)\n  Form 4 \u00b7 2026-02-12 \u00b7 Cap $3.48T\n  90d: BEARISH \u00b7 10b5-1 plan",
  sec:"\u2b2c SECTORS (30d):\n  Tech    \u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501 42% SELL\n  Finance \u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501 28% mixed\n  Health  \u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501 15% BUY\n  Energy  \u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501 10%"
};

/*  FEATURE REGISTRY  */
var CATS = [
  {cat:"Market Data",icon:"\u25C8",features:[
    {id:"trades_feed",name:"Insider Trades Feed",icon:"\uD83D\uDCCB"},
    {id:"heatmap",name:"Sector Heat Map",icon:"\u25A6"},
    {id:"candlestick",name:"Candlestick Chart",icon:"\u25F0"},
    {id:"line_chart",name:"Line / Area Chart",icon:"\u25F3"},
    {id:"volume_chart",name:"Volume Chart",icon:"\u25A5"}
  ]},
  {cat:"Analysis",icon:"\u2211",features:[
    {id:"quant",name:"Quantitative Metrics",icon:"\u2211"},
    {id:"balance_sankey",name:"Balance Sheet Sankey",icon:"\u25E7"},
    {id:"balance_tree",name:"Balance Treemap",icon:"\u25EB"},
    {id:"scatter",name:"Trade Size vs Cap",icon:"\u25CC"}
  ]},
  {cat:"Network",icon:"\u25CE",features:[
    {id:"board_network",name:"Board & Shareholder Map",icon:"\u25CE"},
    {id:"diorama_3d",name:"3D Trade Diorama",icon:"\u25C6"}
  ]},
  {cat:"Intelligence",icon:"\u25B8",features:[
    {id:"ai_terminal",name:"AI Terminal",icon:"\u25B8"},
    {id:"flagged_alerts",name:"Flagged Alerts",icon:"\u2691"},
    {id:"data_sources",name:"Data Sources",icon:"\u26A1"}
  ]}
];

var ALL_F = [];
CATS.forEach(function(c){ c.features.forEach(function(f){ ALL_F.push(f); }); });

function fmt(n) {
  if(n>=1e12) return "$"+(n/1e12).toFixed(2)+"T";
  if(n>=1e9) return "$"+(n/1e9).toFixed(1)+"B";
  if(n>=1e6) return "$"+(n/1e6).toFixed(1)+"M";
  if(n>=1e3) return "$"+(n/1e3).toFixed(0)+"K";
  return "$"+n;
}

function hCol(ch, t) {
  if(ch>=4)return t.h5; if(ch>=2.5)return t.h4; if(ch>=1)return t.h3; if(ch>=0.3)return t.h2;
  if(ch>=-0.3)return t.muted; if(ch>=-1)return t.n2; if(ch>=-2.5)return t.n3;
  if(ch>=-4)return t.n4; return t.n5;
}

function runAI(cmd) {
  var q = cmd.toLowerCase();
  if(q.indexOf("flag")>=0) return AIR.flag;
  if(q.indexOf("sell")>=0||q.indexOf("top")>=0) return AIR.sell;
  if(q.indexOf("nvda")>=0) return AIR.nvda;
  if(q.indexOf("sector")>=0) return AIR.sec;
  if(q.indexOf("help")>=0) return "Commands: flagged, top sells, NVDA, sector, help";
  return "Querying \""+cmd+"\"...";
}

/*  SIZES  */
var SIZES = {
  quarter:{l:"\u00BC",gc:"span 1",gr:"span 1"},
  half_h:{l:"\u00BDW",gc:"span 2",gr:"span 1"},
  half_v:{l:"\u00BDH",gc:"span 1",gr:"span 2"},
  full:{l:"Full",gc:"span 2",gr:"span 2"}
};
var SIZE_KEYS = ["quarter","half_h","half_v","full"];

var winCounter = 0;
function mkWin(fid, sz) {
  var f = null;
  for (var fi = 0; fi < ALL_F.length; fi++) { if(ALL_F[fi].id === fid) { f = ALL_F[fi]; break; } }
  winCounter++;
  return { wid: winCounter, fid: fid, name: f ? f.name : fid, icon: f ? f.icon : "?", size: sz || "quarter", min: false };
}

/* ═══════════════════════════════════════════════════════════════════════════
   WINDOW COMPONENTS — now use DataContext for live data
   ═══════════════════════════════════════════════════════════════════════════ */

function TradesFeed(props) {
  var t = props.t;
  var dataLayer = useContext(DataContext);
  var sortState = useState("date");
  var sb = sortState[0], setSb = sortState[1];
  var flagState = useState(false);
  var ff = flagState[0], setFf = flagState[1];

  var liveTrades = (dataLayer && dataLayer.trades.length > 0) ? dataLayer.trades : TRADES;

  var sorted = useMemo(function() {
    var a = ff ? liveTrades.filter(function(x){return x.flagged;}) : liveTrades.slice();
    if(sb==="cap") a.sort(function(a,b){return (b.cap||0)-(a.cap||0);});
    else if(sb==="size") a.sort(function(a,b){return b.value-a.value;});
    else a.sort(function(a,b){return b.date>a.date?1:-1;});
    return a;
  }, [sb, ff, liveTrades]);

  return React.createElement("div", {style:{height:"100%",display:"flex",flexDirection:"column"}},
    React.createElement("div", {style:{display:"flex",gap:3,marginBottom:5,flexWrap:"wrap",alignItems:"center"}},
      [["date","Recent"],["cap","Mkt Cap"],["size","Size"]].map(function(arr){
        return React.createElement("button", {key:arr[0], onClick:function(){setSb(arr[0]);},
          style:{background:sb===arr[0]?t.accent+"20":"transparent",border:"1px solid "+(sb===arr[0]?t.accent:t.border),
          color:sb===arr[0]?t.accent:t.muted,padding:"2px 6px",fontSize:8,cursor:"pointer",fontFamily:"inherit"}}, arr[1]);
      }),
      React.createElement("button", {onClick:function(){setFf(!ff);},
        style:{background:ff?t.warn+"20":"transparent",border:"1px solid "+(ff?t.warn:t.border),
        color:ff?t.warn:t.muted,padding:"2px 6px",fontSize:8,cursor:"pointer",fontFamily:"inherit"}}, "\u2691 Flagged"),
      dataLayer && dataLayer.trades.length > 0 ? React.createElement("span", {style:{fontSize:7,color:t.buy,marginLeft:4}}, "\u25CF LIVE") : React.createElement("span", {style:{fontSize:7,color:t.muted,marginLeft:4}}, "\u25CB MOCK")
    ),
    React.createElement("div", {style:{flex:1,overflow:"auto",fontSize:9}},
      React.createElement("table", {style:{width:"100%",borderCollapse:"collapse"}},
        React.createElement("thead", null,
          React.createElement("tr", {style:{borderBottom:"1px solid "+t.border,color:t.muted,fontSize:7,textAlign:"left"}},
            React.createElement("th", {style:{padding:3}}, "DATE"),
            React.createElement("th", {style:{padding:3}}, "INSIDER"),
            React.createElement("th", {style:{padding:3}}, "TKR"),
            React.createElement("th", {style:{padding:3}}, "TYPE"),
            React.createElement("th", {style:{padding:3,textAlign:"right"}}, "VALUE"),
            React.createElement("th", {style:{padding:3,textAlign:"right"}}, "CAP"),
            React.createElement("th", {style:{padding:3,textAlign:"center"}}, "\u2691")
          )
        ),
        React.createElement("tbody", null,
          sorted.map(function(r, idx) {
            var bg = r.flagged ? t.warn+"06" : idx%2 ? t.bgAlt+"30" : "transparent";
            return React.createElement("tr", {key:r.id||idx,
              style:{borderBottom:"1px solid "+t.border+"10",background:bg,cursor:"pointer"},
              onMouseEnter:function(e){e.currentTarget.style.background=t.highlight;},
              onMouseLeave:function(e){e.currentTarget.style.background=bg;}},
              React.createElement("td", {style:{padding:3,color:t.muted,fontSize:8}}, (r.date||'').slice(5)),
              React.createElement("td", {style:{padding:3}},
                React.createElement("span", {style:{color:t.textBright}}, r.insider),
                " ",
                React.createElement("span", {style:{color:t.muted,fontSize:7}}, r.title)
              ),
              React.createElement("td", {style:{padding:3,color:t.accent,fontWeight:700}}, r.ticker),
              React.createElement("td", {style:{padding:3}},
                React.createElement("span", {style:{color:r.type==="BUY"?t.buy:t.sell,fontWeight:700,fontSize:8,background:(r.type==="BUY"?t.buy:t.sell)+"15",padding:"1px 3px"}}, r.type)
              ),
              React.createElement("td", {style:{padding:3,textAlign:"right",color:t.textBright,fontWeight:600}}, fmt(r.value)),
              React.createElement("td", {style:{padding:3,textAlign:"right",color:t.muted,fontSize:8}}, r.cap ? fmt(r.cap) : "—"),
              React.createElement("td", {style:{padding:3,textAlign:"center"}},
                r.flagged ? React.createElement("span", {title:r.reason,style:{color:t.warn,cursor:"help"}}, "\u2691") : null
              )
            );
          })
        )
      )
    )
  );
}

function HeatmapComp(props) {
  var t = props.t;
  var dataLayer = useContext(DataContext);
  var liveSectors = (dataLayer && dataLayer.sectors.length > 0) ? dataLayer.sectors : SECTORS;

  var items = liveSectors.map(function(sec) {
    var tiles = sec.tickers.map(function(tk) {
      var col = hCol(tk.c, t);
      return React.createElement("div", {key:tk.t, title:tk.t+": "+(tk.c>0?"+":"")+tk.c+"%",
        style:{background:col+"20",border:"1px solid "+col+"40",padding:"2px 4px",fontSize:7,
          cursor:"pointer",minWidth:38,textAlign:"center",lineHeight:1.4,transition:"all .15s"},
        onMouseEnter:function(e){e.currentTarget.style.background=col+"45";e.currentTarget.style.transform="scale(1.08)";},
        onMouseLeave:function(e){e.currentTarget.style.background=col+"20";e.currentTarget.style.transform="scale(1)";}},
        React.createElement("div", {style:{color:t.textBright,fontWeight:700}}, tk.t),
        React.createElement("div", {style:{color:col,fontWeight:600}}, (tk.c>0?"+":"")+tk.c+"%")
      );
    });
    return React.createElement("div", {key:sec.sector},
      React.createElement("div", {style:{display:"flex",justifyContent:"space-between",marginBottom:2,alignItems:"center"}},
        React.createElement("span", {style:{fontSize:9,fontWeight:700,color:t.textBright}}, sec.sector),
        React.createElement("span", {style:{fontSize:8,color:hCol(sec.change,t),fontWeight:700}}, (sec.change>0?"+":"")+sec.change+"% "+(sec.mcap||""))
      ),
      React.createElement("div", {style:{display:"flex",flexWrap:"wrap",gap:2}}, tiles)
    );
  });

  var gradient = [t.n5,t.n4,t.n3,t.n2,t.muted,t.h2,t.h3,t.h4,t.h5].map(function(c,gi){
    return React.createElement("div", {key:gi, style:{flex:1,background:c}});
  });

  return React.createElement("div", {style:{height:"100%",overflow:"auto",display:"flex",flexDirection:"column",gap:5}},
    items,
    React.createElement("div", {style:{display:"flex",justifyContent:"center",gap:4,paddingTop:4,borderTop:"1px solid "+t.border+"20",alignItems:"center"}},
      React.createElement("span", {style:{fontSize:7,color:t.muted}}, "-4%"),
      React.createElement("div", {style:{display:"flex",height:6,width:140}}, gradient),
      React.createElement("span", {style:{fontSize:7,color:t.muted}}, "+4%")
    )
  );
}

function CandleComp(props) {
  var t = props.t;
  var dataLayer = useContext(DataContext);
  var candleState = useState(CANDLE);
  var liveCandles = candleState[0], setLiveCandles = candleState[1];

  useEffect(function() {
    if (dataLayer && dataLayer.refreshCandles) {
      dataLayer.refreshCandles('NVDA').then(function(data) {
        if (data && data.length > 0) setLiveCandles(data);
      }).catch(function() {});
    }
  }, [dataLayer]);

  var ref = useRef(null);
  useEffect(function() {
    var cv = ref.current; if(!cv) return;
    var ctx = cv.getContext("2d");
    var w = cv.width = cv.parentElement.offsetWidth;
    var h = cv.height = cv.parentElement.offsetHeight;
    ctx.clearRect(0,0,w,h);
    var aH = -Infinity, aL = Infinity;
    liveCandles.forEach(function(d){if(d.high>aH)aH=d.high;if(d.low<aL)aL=d.low;});
    var rng = aH-aL||1;
    var bw = Math.max(2,(w-20)/liveCandles.length-1.5);
    liveCandles.forEach(function(d,i){
      var x=10+i*((w-20)/liveCandles.length);
      var oY=h-((d.open-aL)/rng)*(h-20)-10;
      var cY=h-((d.close-aL)/rng)*(h-20)-10;
      var hY=h-((d.high-aL)/rng)*(h-20)-10;
      var lY=h-((d.low-aL)/rng)*(h-20)-10;
      var bull=d.close>=d.open;
      ctx.strokeStyle=bull?t.buy:t.sell;ctx.fillStyle=bull?t.buy:t.sell;
      ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(x+bw/2,hY);ctx.lineTo(x+bw/2,lY);ctx.stroke();
      ctx.globalAlpha=0.85;ctx.fillRect(x,Math.min(oY,cY),bw,Math.max(1,Math.abs(cY-oY)));ctx.globalAlpha=1;
    });
  }, [t, liveCandles]);
  return React.createElement("canvas", {ref:ref, style:{width:"100%",height:"100%",display:"block"}});
}

function LineComp(props) {
  var t = props.t;
  var dataLayer = useContext(DataContext);
  var candleState = useState(CANDLE);
  var liveCandles = candleState[0], setLiveCandles = candleState[1];

  useEffect(function() {
    if (dataLayer && dataLayer.refreshCandles) {
      dataLayer.refreshCandles('NVDA').then(function(data) {
        if (data && data.length > 0) setLiveCandles(data);
      }).catch(function() {});
    }
  }, [dataLayer]);

  return React.createElement(ResponsiveContainer, {width:"100%",height:"100%"},
    React.createElement(AreaChart, {data:liveCandles},
      React.createElement("defs", null,
        React.createElement("linearGradient", {id:"lg1",x1:"0",y1:"0",x2:"0",y2:"1"},
          React.createElement("stop", {offset:"5%",stopColor:t.accent,stopOpacity:0.3}),
          React.createElement("stop", {offset:"95%",stopColor:t.accent,stopOpacity:0})
        )
      ),
      React.createElement(CartesianGrid, {strokeDasharray:"3 3",stroke:t.border+"40"}),
      React.createElement(XAxis, {dataKey:"date",tick:{fontSize:7,fill:t.muted},tickLine:false,axisLine:{stroke:t.border},interval:9}),
      React.createElement(YAxis, {tick:{fontSize:7,fill:t.muted},tickLine:false,axisLine:{stroke:t.border},domain:["auto","auto"]}),
      React.createElement(Tooltip, {contentStyle:{background:t.bgPanel,border:"1px solid "+t.border,fontSize:8,fontFamily:"inherit",color:t.text}}),
      React.createElement(Area, {type:"monotone",dataKey:"close",stroke:t.accent,fill:"url(#lg1)",strokeWidth:1.5,dot:false})
    )
  );
}

function VolComp(props) {
  var t = props.t;
  var dataLayer = useContext(DataContext);
  var candleState = useState(CANDLE);
  var liveCandles = candleState[0], setLiveCandles = candleState[1];

  useEffect(function() {
    if (dataLayer && dataLayer.refreshCandles) {
      dataLayer.refreshCandles('NVDA').then(function(data) {
        if (data && data.length > 0) setLiveCandles(data);
      }).catch(function() {});
    }
  }, [dataLayer]);

  return React.createElement(ResponsiveContainer, {width:"100%",height:"100%"},
    React.createElement(BarChart, {data:liveCandles},
      React.createElement(CartesianGrid, {strokeDasharray:"3 3",stroke:t.border+"40"}),
      React.createElement(XAxis, {dataKey:"date",tick:{fontSize:7,fill:t.muted},tickLine:false,axisLine:{stroke:t.border},interval:9}),
      React.createElement(YAxis, {tick:{fontSize:7,fill:t.muted},tickLine:false,axisLine:{stroke:t.border},tickFormatter:function(v){return (v/1e6).toFixed(0)+"M";}}),
      React.createElement(Tooltip, {contentStyle:{background:t.bgPanel,border:"1px solid "+t.border,fontSize:8,fontFamily:"inherit",color:t.text}}),
      React.createElement(Bar, {dataKey:"volume",fill:t.accent+"60"})
    )
  );
}

function QuantComp(props) {
  var t = props.t;
  return React.createElement("div", {style:{height:"100%",display:"flex",flexDirection:"column"}},
    React.createElement("div", {style:{flex:1}},
      React.createElement(ResponsiveContainer, {width:"100%",height:"100%"},
        React.createElement(ComposedChart, {data:QUANT},
          React.createElement(CartesianGrid, {strokeDasharray:"3 3",stroke:t.border+"30"}),
          React.createElement(XAxis, {dataKey:"day",tick:{fontSize:7,fill:t.muted},tickLine:false,axisLine:{stroke:t.border}}),
          React.createElement(YAxis, {yAxisId:"l",tick:{fontSize:7,fill:t.muted},tickLine:false,axisLine:{stroke:t.border}}),
          React.createElement(YAxis, {yAxisId:"r",orientation:"right",tick:{fontSize:7,fill:t.muted},tickLine:false,axisLine:{stroke:t.border}}),
          React.createElement(Tooltip, {contentStyle:{background:t.bgPanel,border:"1px solid "+t.border,fontSize:8,fontFamily:"inherit",color:t.text}}),
          React.createElement(Line, {yAxisId:"l",type:"monotone",dataKey:"alpha",stroke:t.accent,strokeWidth:1.5,dot:false}),
          React.createElement(Line, {yAxisId:"l",type:"monotone",dataKey:"sharpe",stroke:t.warn,strokeWidth:1.5,dot:false}),
          React.createElement(Bar, {yAxisId:"r",dataKey:"vol",fill:t.sell+"30"})
        )
      )
    ),
    React.createElement("div", {style:{display:"flex",gap:10,justifyContent:"center",padding:"3px 0",fontSize:7}},
      React.createElement("span", null, React.createElement("span",{style:{color:t.accent}},"\u2501"), " Alpha"),
      React.createElement("span", null, React.createElement("span",{style:{color:t.warn}},"\u2501"), " Sharpe"),
      React.createElement("span", null, React.createElement("span",{style:{color:t.sell+"60"}},"\u2588"), " Vol")
    )
  );
}

function SankeyComp(props) {
  var t = props.t;
  var dataLayer = useContext(DataContext);
  var finState = useState(null);
  var financials = finState[0], setFinancials = finState[1];

  useEffect(function() {
    if (dataLayer && dataLayer.getBalanceSheet) {
      dataLayer.getBalanceSheet('AAPL').then(function(data) {
        if (data && data.length > 0) setFinancials(data[0]);
      }).catch(function() {});
    }
  }, [dataLayer]);

  var ref = useRef(null);
  useEffect(function() {
    var cv = ref.current; if(!cv) return;
    var ctx = cv.getContext("2d");
    var w = cv.width = cv.parentElement.offsetWidth;
    var h = cv.height = cv.parentElement.offsetHeight;
    ctx.clearRect(0,0,w,h);
    var p=10,cW=Math.min(72,w*0.18),c1=p,c2=w/2-cW/2,c3=w-cW-p,rH=h-25;

    // Use live data if available
    var rev = financials ? financials.revenue : 383e9;
    var prod = financials ? financials.grossProfit : 238e9;
    var svc = financials ? (financials.revenue - financials.grossProfit) : 145e9;
    var revFmt = "$" + (rev/1e9).toFixed(0) + "B";
    var prodFmt = "$" + (prod/1e9).toFixed(0) + "B";
    var svcFmt = "$" + (svc/1e9).toFixed(0) + "B";

    var box = function(x,y,bw,bh,col,lbl,sub){
      ctx.fillStyle=col+"25";ctx.strokeStyle=col;ctx.lineWidth=1;ctx.fillRect(x,y,bw,bh);ctx.strokeRect(x,y,bw,bh);
      ctx.fillStyle=col;ctx.font="bold "+Math.min(8,w/42)+"px 'IBM Plex Mono',monospace";ctx.textAlign="center";ctx.fillText(lbl,x+bw/2,y-2);
      if(sub){ctx.font=Math.min(7,w/48)+"px 'IBM Plex Mono',monospace";ctx.fillText(sub,x+bw/2,y+bh+9);}
    };
    var flow = function(x1,y1,h1,x2,y2,h2,col){
      ctx.beginPath();ctx.moveTo(x1,y1);ctx.bezierCurveTo(x1+(x2-x1)*0.5,y1,x2-(x2-x1)*0.5,y2,x2,y2);
      ctx.lineTo(x2,y2+h2);ctx.bezierCurveTo(x2-(x2-x1)*0.5,y2+h2,x1+(x2-x1)*0.5,y1+h1,x1,y1+h1);
      ctx.closePath();ctx.fillStyle=col+"10";ctx.fill();
    };
    box(c1,12,cW,rH,t.accent,"REVENUE",revFmt);
    var pH=rH*0.6,sH=rH*0.36;
    box(c2,12,cW,pH,t.buy,"PRODUCTS",prodFmt);
    box(c2,12+pH+rH*0.04,cW,sH,t.warn,"SERVICES",svcFmt);
    flow(c1+cW,12,pH,c2,12,pH,t.buy);
    flow(c1+cW,12+pH,sH,c2,12+pH+rH*0.04,sH,t.warn);
    var subs=[{n:"iPhone",v:"$146B",p:0.38,col:t.buy},{n:"Mac",v:"$54B",p:0.14,col:t.buy},{n:"iPad",v:"$38B",p:0.10,col:t.buy},{n:"App Store",v:"$69B",p:0.18,col:t.warn},{n:"Cloud",v:"$46B",p:0.12,col:t.warn},{n:"Other",v:"$30B",p:0.08,col:t.muted}];
    var sy=12;
    subs.forEach(function(s){var sh=rH*s.p;ctx.fillStyle=s.col+"18";ctx.strokeStyle=s.col;ctx.lineWidth=1;ctx.fillRect(c3,sy,cW,sh-2);ctx.strokeRect(c3,sy,cW,sh-2);ctx.fillStyle=s.col;ctx.font="bold "+Math.min(7,w/55)+"px 'IBM Plex Mono',monospace";ctx.textAlign="center";if(sh>16){ctx.fillText(s.n,c3+cW/2,sy+sh/2-2);ctx.font=Math.min(6,w/60)+"px 'IBM Plex Mono',monospace";ctx.fillText(s.v,c3+cW/2,sy+sh/2+7);}sy+=sh;});
  }, [t, financials]);
  return React.createElement("canvas", {ref:ref, style:{width:"100%",height:"100%",display:"block"}});
}

function TreeComp(props) {
  var t = props.t;
  return React.createElement(ResponsiveContainer, {width:"100%",height:"100%"},
    React.createElement(Treemap, {data:BTREE,dataKey:"size",nameKey:"name",stroke:t.bg,
      content:function(p){
        if(p.width<22||p.height<16) return null;
        return React.createElement("g", {key:p.name},
          React.createElement("rect", {x:p.x,y:p.y,width:p.width,height:p.height,fill:p.fill||t.accent,stroke:t.bg,strokeWidth:2,rx:1,opacity:0.8}),
          p.width>38&&p.height>20 ? React.createElement("text", {x:p.x+p.width/2,y:p.y+p.height/2,textAnchor:"middle",dominantBaseline:"middle",fill:t.textBright,fontSize:7,fontFamily:"'IBM Plex Mono',monospace"}, p.name) : null
        );
      }
    })
  );
}

function ScatterComp(props) {
  var t = props.t;
  var dataLayer = useContext(DataContext);
  var liveTrades = (dataLayer && dataLayer.trades.length > 0) ? dataLayer.trades : TRADES;
  var data = liveTrades.map(function(x){return {cap:x.cap||0,val:x.value,shares:x.shares};});
  return React.createElement(ResponsiveContainer, {width:"100%",height:"100%"},
    React.createElement(ScatterChart, null,
      React.createElement(CartesianGrid, {strokeDasharray:"3 3",stroke:t.border+"30"}),
      React.createElement(XAxis, {dataKey:"cap",tick:{fontSize:7,fill:t.muted},tickFormatter:function(v){return "$"+(v/1e12).toFixed(1)+"T";},axisLine:{stroke:t.border}}),
      React.createElement(YAxis, {dataKey:"val",tick:{fontSize:7,fill:t.muted},tickFormatter:function(v){return "$"+(v/1e6).toFixed(0)+"M";},axisLine:{stroke:t.border}}),
      React.createElement(ZAxis, {dataKey:"shares",range:[30,300]}),
      React.createElement(Tooltip, {contentStyle:{background:t.bgPanel,border:"1px solid "+t.border,fontSize:8,fontFamily:"inherit",color:t.text}}),
      React.createElement(Scatter, {data:data,fill:t.accent})
    )
  );
}

function NetworkComp(props) {
  var t = props.t;
  var ref = useRef(null);
  useEffect(function() {
    var cv = ref.current; if(!cv) return;
    var ctx = cv.getContext("2d");
    var w = cv.width = cv.parentElement.offsetWidth;
    var h = cv.height = cv.parentElement.offsetHeight;
    ctx.clearRect(0,0,w,h);
    BOARD.forEach(function(n){if(!n.conn)return;n.conn.forEach(function(cid){
      var tg=null;BOARD.forEach(function(x){if(x.id===cid)tg=x;});
      if(tg){ctx.beginPath();ctx.moveTo(n.x/100*w,n.y/100*h);ctx.lineTo(tg.x/100*w,tg.y/100*h);ctx.strokeStyle=t.border;ctx.lineWidth=1;ctx.setLineDash([3,3]);ctx.stroke();ctx.setLineDash([]);}
    });});
    BOARD.forEach(function(n){
      var x=n.x/100*w,y=n.y/100*h,isC=n.type==="co",r=isC?15:10;
      ctx.beginPath();
      if(isC){ctx.rect(x-r,y-r*0.7,r*2,r*1.4);ctx.fillStyle=t.accent+"25";ctx.strokeStyle=t.accent;}
      else{ctx.arc(x,y,r,0,Math.PI*2);ctx.fillStyle=t.warn+"25";ctx.strokeStyle=t.warn;}
      ctx.fill();ctx.lineWidth=1.5;ctx.stroke();
      ctx.fillStyle=isC?t.accent:t.textBright;ctx.font=(isC?"bold ":"")+Math.min(8,w/32)+"px 'IBM Plex Mono',monospace";ctx.textAlign="center";
      ctx.fillText(n.name,x,y+(isC?3:-r-3));
      if(n.role){ctx.fillStyle=t.muted;ctx.font=Math.min(7,w/40)+"px 'IBM Plex Mono',monospace";ctx.fillText(n.role+" \u00B7 "+n.sh,x,y+r+8);}
    });
  }, [t]);
  return React.createElement("canvas", {ref:ref, style:{width:"100%",height:"100%",display:"block"}});
}

function DioramaComp(props) {
  var dataLayer = useContext(DataContext);
  var liveTrades = (dataLayer && dataLayer.trades.length > 0) ? dataLayer.trades : TRADES;
  var mountRef = useRef(null);
  var initRef = useRef(false);
  useEffect(function() {
    if(!mountRef.current || initRef.current) return;
    initRef.current = true;
    var el = mountRef.current;
    var scene = new THREE.Scene();
    var cam = new THREE.PerspectiveCamera(60, el.offsetWidth / Math.max(el.offsetHeight,1), 0.1, 1000);
    var ren = new THREE.WebGLRenderer({antialias:true, alpha:true});
    ren.setSize(el.offsetWidth, el.offsetHeight);
    ren.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    el.appendChild(ren.domElement);
    cam.position.set(8,6,12);cam.lookAt(0,0,0);
    scene.add(new THREE.AmbientLight(0x334455,0.6));
    var dl = new THREE.DirectionalLight(0x00ff9d,0.8);dl.position.set(5,10,7);scene.add(dl);
    scene.add(new THREE.GridHelper(20,20,0x1e4d3a,0x0d2818));
    var trs = liveTrades.slice(0,8);
    var mx = 0; trs.forEach(function(x){if(x.value>mx)mx=x.value;});
    trs.forEach(function(tr,i){
      var h2 = (tr.value/mx)*6+0.5;
      var col = tr.flagged?0xffc940:tr.type==="BUY"?0x00ff9d:0xff3366;
      var geo = new THREE.BoxGeometry(0.7,h2,0.7);
      var mat = new THREE.MeshPhongMaterial({color:col,transparent:true,opacity:0.85,emissive:col,emissiveIntensity:0.15});
      var mesh = new THREE.Mesh(geo,mat);
      var angle = (i/trs.length)*Math.PI*2;
      mesh.position.set(Math.cos(angle)*5,h2/2,Math.sin(angle)*5);scene.add(mesh);
      var sp = new THREE.Mesh(new THREE.SphereGeometry(0.15,8,8),new THREE.MeshPhongMaterial({color:col,emissive:col,emissiveIntensity:0.5}));
      sp.position.set(mesh.position.x,h2+0.4,mesh.position.z);scene.add(sp);
      var pts = [new THREE.Vector3(0,0.1,0),new THREE.Vector3(mesh.position.x,0.1,mesh.position.z)];
      scene.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts),new THREE.LineBasicMaterial({color:col,transparent:true,opacity:0.3})));
    });
    scene.add(new THREE.Mesh(new THREE.SphereGeometry(0.4,16,16),new THREE.MeshPhongMaterial({color:0x00ff9d,emissive:0x00ff9d,emissiveIntensity:0.3})));
    var frame;
    var animate = function(){frame=requestAnimationFrame(animate);var tt=Date.now()*0.001;cam.position.x=Math.cos(tt*0.2)*14;cam.position.z=Math.sin(tt*0.2)*14;cam.position.y=6+Math.sin(tt*0.3)*2;cam.lookAt(0,1.5,0);ren.render(scene,cam);};
    animate();
    return function(){cancelAnimationFrame(frame);if(el.contains(ren.domElement))el.removeChild(ren.domElement);initRef.current=false;};
  }, []);
  return React.createElement("div", {ref:mountRef, style:{width:"100%",height:"100%",minHeight:120}});
}

function AiTermComp(props) {
  var t = props.t;
  var dataLayer = useContext(DataContext);
  var valS = useState(""); var val = valS[0], setVal = valS[1];
  var histS = useState([]); var hist = histS[0], setHist = histS[1];
  var doRun = function(cmd) {
    if (dataLayer && dataLayer.handleQuery) {
      dataLayer.handleQuery(cmd).then(function(r) {
        setHist(function(prev){return prev.concat([{cmd:cmd,resp:r}]);});
      });
    } else {
      var r = runAI(cmd);
      setHist(function(prev){return prev.concat([{cmd:cmd,resp:r}]);});
    }
    setVal("");
  };
  return React.createElement("div", {style:{height:"100%",display:"flex",flexDirection:"column"}},
    React.createElement("div", {style:{display:"flex",border:"1px solid "+t.border,background:t.inputBg,marginBottom:4}},
      React.createElement("span", {style:{padding:"4px 6px",color:t.accent,fontSize:10}}, "\u276F"),
      React.createElement("input", {value:val,onChange:function(e){setVal(e.target.value);},onKeyDown:function(e){if(e.key==="Enter"&&val.trim())doRun(val);},placeholder:"query...",style:{flex:1,background:"transparent",border:"none",outline:"none",color:t.textBright,fontFamily:"inherit",fontSize:9,padding:4}})
    ),
    React.createElement("div", {style:{fontSize:7,color:t.muted,marginBottom:3}},
      ["flagged","top sells","sector","NVDA"].map(function(q){return React.createElement("span",{key:q,onClick:function(){doRun(q);},style:{color:t.accent,cursor:"pointer",marginRight:5}},"["+q+"]");})
    ),
    React.createElement("div", {style:{flex:1,overflow:"auto",fontSize:8,lineHeight:1.7,whiteSpace:"pre-wrap",color:t.text,background:t.bg,border:"1px solid "+t.border+"15",padding:5}},
      hist.slice(-4).map(function(h,idx){return React.createElement("div",{key:idx,style:{marginBottom:5}},React.createElement("div",{style:{color:t.accent}},"\u276F "+h.cmd),React.createElement("div",{style:{marginTop:1}},h.resp),React.createElement("div",{style:{borderBottom:"1px solid "+t.border+"20",margin:"3px 0"}}));}),
      hist.length===0 ? React.createElement("div",{style:{color:t.accent}},AIR.def) : null
    )
  );
}

function FlagComp(props) {
  var t = props.t;
  var dataLayer = useContext(DataContext);
  var liveTrades = (dataLayer && dataLayer.trades.length > 0) ? dataLayer.trades : TRADES;
  var flagged = liveTrades.filter(function(x){return x.flagged;});
  return React.createElement("div", {style:{display:"flex",flexDirection:"column",gap:5,overflow:"auto",height:"100%"}},
    flagged.length === 0 ? React.createElement("div", {style:{color:t.muted,fontSize:9,padding:10}}, "Scanning for flagged trades...") : null,
    flagged.map(function(r, idx){
      return React.createElement("div", {key:r.id||idx, style:{border:"1px solid "+t.warn+"30",background:t.warn+"08",padding:6}},
        React.createElement("div", {style:{display:"flex",justifyContent:"space-between",marginBottom:2}},
          React.createElement("span", {style:{color:t.warn,fontWeight:700,fontSize:9}}, "\u2691 "+r.ticker+" \u2014 "+r.type),
          React.createElement("span", {style:{color:t.muted,fontSize:7}}, r.date)
        ),
        React.createElement("div", {style:{fontSize:8,color:t.textBright}}, r.insider+" ("+r.title+") \u2014 "+fmt(r.value)),
        React.createElement("div", {style:{fontSize:7,color:t.warn,marginTop:2,fontStyle:"italic"}}, r.reason)
      );
    })
  );
}

function SrcComp(props) {
  var t = props.t;
  var dataLayer = useContext(DataContext);
  var fallbackSrcs = [{n:"SEC EDGAR",s:"IDLE",l:"\u2014"},{n:"Polygon.io Pro",s:"IDLE",l:"\u2014"},{n:"News / Sentiment",s:"IDLE",l:"\u2014"}];
  var srcs = (dataLayer && dataLayer.getDataSourceStatus) ? dataLayer.getDataSourceStatus() : fallbackSrcs;
  return React.createElement("div", null, srcs.map(function(s){
    var col = s.s==="LIVE"?t.buy:s.s==="ERROR"?t.sell:s.s==="LOADING"?t.warn:t.muted;
    return React.createElement("div", {key:s.n, style:{display:"flex",justifyContent:"space-between",padding:"4px 0",borderBottom:"1px solid "+t.border+"15",fontSize:9}},
      React.createElement("span", null, s.n),
      React.createElement("span", null,
        React.createElement("span", {style:{color:t.muted,fontSize:7,marginRight:4}}, s.l),
        React.createElement("span", {style:{color:col,fontSize:7}}, "\u25CF "+s.s)
      )
    );
  }));
}

/*  RENDER MAP  */
var RMAP = {
  trades_feed: TradesFeed,
  heatmap: HeatmapComp,
  candlestick: CandleComp,
  line_chart: LineComp,
  volume_chart: VolComp,
  quant: QuantComp,
  balance_sankey: SankeyComp,
  balance_tree: TreeComp,
  scatter: ScatterComp,
  board_network: NetworkComp,
  diorama_3d: DioramaComp,
  ai_terminal: AiTermComp,
  flagged_alerts: FlagComp,
  data_sources: SrcComp
};

/* ═══════════════════════════════════════════════════════════════════════════
   MAIN APP
   ═══════════════════════════════════════════════════════════════════════════ */
export default function WhaleWatch() {
  var modeS = useState("dark"); var mode = modeS[0], setMode = modeS[1];
  var nowS = useState(new Date()); var now = nowS[0], setNow = nowS[1];
  var winsS = useState([mkWin("trades_feed","half_h"),mkWin("heatmap","half_h"),mkWin("candlestick","quarter"),mkWin("ai_terminal","quarter"),mkWin("diorama_3d","quarter"),mkWin("quant","quarter")]);
  var wins = winsS[0], setWins = winsS[1];
  var ddS = useState(false); var ddOpen = ddS[0], setDdOpen = ddS[1];
  var cmdS = useState(""); var cmd = cmdS[0], setCmd = cmdS[1];
  var cmdHS = useState([]); var cmdH = cmdHS[0], setCmdH = cmdHS[1];
  var ddRef = useRef(null);
  var t = themes[mode];

  // Live data layer — polls every 60s
  var dataLayer = useWhaleWatchData(60000);

  useEffect(function(){var iv=setInterval(function(){setNow(new Date());},1000);return function(){clearInterval(iv);};}, []);
  useEffect(function(){var h=function(e){if(ddRef.current&&!ddRef.current.contains(e.target))setDdOpen(false);};document.addEventListener("mousedown",h);return function(){document.removeEventListener("mousedown",h);};},[]);

  var addWin = function(fid,sz){setWins(function(w){return w.concat([mkWin(fid,sz||"quarter")]);});setDdOpen(false);};
  var rmWin = function(wid){setWins(function(w){return w.filter(function(x){return x.wid!==wid;});});};
  var togMin = function(wid){setWins(function(w){return w.map(function(x){return x.wid===wid?Object.assign({},x,{min:!x.min}):x;});});};
  var setSz = function(wid,sz){setWins(function(w){return w.map(function(x){return x.wid===wid?Object.assign({},x,{size:sz}):x;});});};

  var doCmd = function(c2) {
    if (dataLayer && dataLayer.handleQuery) {
      dataLayer.handleQuery(c2).then(function(r) {
        setCmdH(function(h){return h.concat([{cmd:c2,resp:r}]);});
      });
    } else {
      var r = runAI(c2);
      setCmdH(function(h){return h.concat([{cmd:c2,resp:r}]);});
    }
    setCmd("");
  };

  var active = wins.filter(function(w){return !w.min;});
  var minimized = wins.filter(function(w){return w.min;});

  // Live market overview for status bar
  var mkt = dataLayer.marketOverview;
  var spxText = mkt && mkt.spx ? "SPX: " + mkt.spx.price.toLocaleString() + (mkt.spx.change > 0 ? " \u25B2" : " \u25BC") + Math.abs(mkt.spx.change).toFixed(2) + "%" : "SPX: 6,142 \u25B20.34%";
  var spxCol = mkt && mkt.spx ? (mkt.spx.change >= 0 ? t.buy : t.sell) : t.buy;

  var liveTradeCount = dataLayer.trades.length > 0 ? dataLayer.trades.length : 47;
  var liveFlagCount = dataLayer.trades.length > 0 ? dataLayer.trades.filter(function(x){return x.flagged;}).length : 4;

  var navItems = [{n:"SEESAW",i:"\u2696",home:true},{n:"MFSES",i:"\u25C8"},{n:"NewsIQ",i:"\uD83D\uDCE1"},{n:"WhaleWatch",i:"\uD83D\uDC0B",active:true},{n:"About",i:"\u2139"},{n:"Account",i:"\u25C9"}];

  return React.createElement(DataContext.Provider, {value: dataLayer},
    React.createElement("div", {style:{background:t.bg,color:t.text,fontFamily:"'IBM Plex Mono','Fira Code',monospace",fontSize:12,height:"100vh",display:"flex",flexDirection:"column",overflow:"hidden",transition:"background .3s,color .3s"}},

    /* scanline */
    React.createElement("div", {style:{position:"fixed",inset:0,background:"repeating-linear-gradient(0deg,transparent,transparent 2px,"+t.accent+"02 2px,"+t.accent+"02 4px)",pointerEvents:"none",zIndex:9999}}),

    /* NAV */
    React.createElement("header", {style:{borderBottom:"1px solid "+t.border,padding:"0 10px",display:"flex",alignItems:"center",justifyContent:"space-between",height:36,background:t.bgPanel,flexShrink:0,zIndex:100}},
      React.createElement("div", {style:{display:"flex",alignItems:"center",gap:4}},
        React.createElement("span", {style:{color:t.accent,fontWeight:900,fontSize:12,letterSpacing:".15em"}}, "\uD83D\uDC0B WHALEWATCH"),
        React.createElement("span", {style:{color:t.muted,fontSize:7,marginLeft:6}}, "v2.1 \u2502 SEC \u00B7 POLYGON \u00B7 REUTERS")
      ),
      React.createElement("nav", {style:{display:"flex",gap:1}},
        navItems.map(function(x){return React.createElement("a",{key:x.n,href:x.n==="MFSES"?"/dashboard":x.n==="SEESAW"?"/":"#",style:{padding:"4px 7px",textDecoration:"none",fontSize:9,color:x.active?t.accent:x.home?t.textBright:t.muted,fontWeight:x.active||x.home?700:400,background:x.active?t.accent+"12":"transparent",border:x.active?"1px solid "+t.border:"1px solid transparent",display:"flex",alignItems:"center",gap:3}},x.i+" "+x.n);})
      ),
      React.createElement("div", {style:{display:"flex",alignItems:"center",gap:5}},
        React.createElement("div", {style:{width:1,height:16,background:t.border}}),
        React.createElement("button", {onClick:function(){setMode(mode==="dark"?"light":"dark");},style:{background:t.accent+"15",border:"1px solid "+t.border,color:t.accent,padding:"2px 7px",cursor:"pointer",fontSize:8,fontFamily:"inherit"}}, mode==="dark"?"\u2600 LIGHT":"\u263E DARK")
      )
    ),

    /* STATUS */
    React.createElement("div", {style:{borderBottom:"1px solid "+t.border,padding:"2px 10px",display:"flex",justifyContent:"space-between",background:t.bgAlt,fontSize:7,color:t.muted,flexShrink:0}},
      React.createElement("div", {style:{display:"flex",gap:12}},
        React.createElement("span",null,dataLayer.loading ? "\u25CB LOADING" : "\u25C9 LIVE"),
        React.createElement("span",null,"MKT: ",React.createElement("span",{style:{color:t.buy}},"OPEN")),
        React.createElement("span",null,React.createElement("span",{style:{color:spxCol}},spxText)),
        React.createElement("span",null,"VIX: ",React.createElement("span",{style:{color:t.sell}},"18.42"))
      ),
      React.createElement("div", {style:{display:"flex",gap:10}},
        React.createElement("span",null,"TRADES: ",React.createElement("span",{style:{color:t.accent}},String(liveTradeCount))),
        React.createElement("span",null,"FLAGGED: ",React.createElement("span",{style:{color:t.warn}},String(liveFlagCount))),
        React.createElement("span",null,now.toLocaleTimeString())
      )
    ),

    /* BODY */
    React.createElement("div", {style:{display:"flex",flex:1,overflow:"hidden"}},

      /* LEFT SIDEBAR */
      React.createElement("aside", {style:{width:240,borderRight:"1px solid "+t.border,display:"flex",flexDirection:"column",flexShrink:0,background:t.bgPanel}},
        React.createElement("div", {style:{padding:7,borderBottom:"1px solid "+t.border}},
          React.createElement("div", {style:{display:"flex",border:"1px solid "+t.border,background:t.inputBg}},
            React.createElement("span", {style:{padding:"4px 5px",color:t.accent,fontSize:10}}, "\u276F"),
            React.createElement("input", {value:cmd,onChange:function(e){setCmd(e.target.value);},onKeyDown:function(e){if(e.key==="Enter"&&cmd.trim())doCmd(cmd);},placeholder:"search / command...",style:{flex:1,background:"transparent",border:"none",outline:"none",color:t.textBright,fontFamily:"inherit",fontSize:9,padding:4}})
          ),
          React.createElement("div", {style:{fontSize:7,color:t.muted,marginTop:3}},
            ["flagged","top sells","sector","NVDA"].map(function(q){return React.createElement("span",{key:q,onClick:function(){doCmd(q);},style:{color:t.accent,cursor:"pointer",marginRight:5}},"["+q+"]");})
          )
        ),
        React.createElement("div", {style:{flex:1,overflow:"auto",padding:7,fontSize:8,lineHeight:1.7,whiteSpace:"pre-wrap",color:t.text}},
          React.createElement("div", {style:{color:t.accent,fontSize:7,fontWeight:700,marginBottom:3,letterSpacing:".1em"}}, "\u2562 AI ASSISTANT \u255F"),
          cmdH.slice(-5).map(function(h,idx){return React.createElement("div",{key:idx,style:{marginBottom:5}},React.createElement("div",{style:{color:t.accent}},"\u276F "+h.cmd),React.createElement("div",{style:{marginTop:1}},h.resp),React.createElement("div",{style:{borderBottom:"1px solid "+t.border+"20",margin:"3px 0"}}));}),
          cmdH.length===0 ? React.createElement("div",{style:{color:t.accent}},AIR.def) : null
        ),
        React.createElement("div", {style:{borderTop:"1px solid "+t.border,padding:7}},
          React.createElement("div", {style:{color:t.accent,fontSize:7,fontWeight:700,marginBottom:3,letterSpacing:".1em"}}, "\u2562 DATA FEEDS \u255F"),
          (dataLayer.getDataSourceStatus ? dataLayer.getDataSourceStatus() : [{n:"SEC EDGAR",s:"IDLE",l:"\u2014"},{n:"Polygon.io",s:"IDLE",l:"\u2014"},{n:"News",s:"IDLE",l:"\u2014"}]).map(function(s){
            var col = s.s==="LIVE"?t.buy:s.s==="ERROR"?t.sell:s.s==="LOADING"?t.warn:t.muted;
            return React.createElement("div",{key:s.n,style:{display:"flex",justifyContent:"space-between",padding:"2px 0",fontSize:8}},React.createElement("span",null,s.n),React.createElement("span",{style:{color:t.muted,fontSize:7}},s.l+" ",React.createElement("span",{style:{color:col}},"\u25CF")));
          })
        ),
        minimized.length>0 ? React.createElement("div", {style:{borderTop:"1px solid "+t.border,padding:7}},
          React.createElement("div", {style:{color:t.warn,fontSize:7,fontWeight:700,marginBottom:3,letterSpacing:".1em"}}, "\u2562 MINIMIZED ("+minimized.length+") \u255F"),
          minimized.map(function(w){return React.createElement("div",{key:w.wid,onClick:function(){togMin(w.wid);},style:{display:"flex",alignItems:"center",gap:3,padding:"2px 3px",cursor:"pointer",fontSize:8,color:t.muted,border:"1px solid "+t.border+"20",marginBottom:2,background:t.bgAlt}},React.createElement("span",null,w.icon),React.createElement("span",{style:{flex:1}},w.name),React.createElement("span",{style:{color:t.accent,fontSize:7}},"\u25B2"));})
        ) : null
      ),

      /* MAIN ENGINE */
      React.createElement("main", {style:{flex:1,display:"flex",flexDirection:"column",overflow:"hidden"}},
        /* Toolbar */
        React.createElement("div", {style:{display:"flex",alignItems:"center",padding:"3px 7px",borderBottom:"1px solid "+t.border,background:t.bgAlt,gap:5,flexShrink:0}},
          React.createElement("div", {ref:ddRef,style:{position:"relative"}},
            React.createElement("button", {onClick:function(){setDdOpen(!ddOpen);},style:{background:t.accent+"15",border:"1px solid "+t.accent+"50",color:t.accent,padding:"2px 8px",cursor:"pointer",fontSize:8,fontFamily:"inherit",display:"flex",alignItems:"center",gap:3}}, "+ Add Window \u25BE"),
            ddOpen ? React.createElement("div", {style:{position:"absolute",top:"100%",left:0,marginTop:2,background:t.bgPanel,border:"1px solid "+t.border,zIndex:200,width:300,maxHeight:420,overflowY:"auto",boxShadow:"0 8px 32px "+t.bg+"80"}},
              CATS.map(function(cat){return React.createElement("div",{key:cat.cat},
                React.createElement("div",{style:{padding:"5px 8px",color:t.accent,fontSize:7,fontWeight:700,letterSpacing:".1em",background:t.bgAlt,borderBottom:"1px solid "+t.border+"20"}},cat.icon+" "+cat.cat.toUpperCase()),
                cat.features.map(function(f){
                  var exists=false;wins.forEach(function(w){if(w.fid===f.id&&!w.min)exists=true;});
                  return React.createElement("div",{key:f.id,style:{padding:"4px 8px 4px 16px",fontSize:8,color:exists?t.muted:t.textBright,display:"flex",justifyContent:"space-between",alignItems:"center",cursor:exists?"default":"pointer"}},
                    React.createElement("span",null,f.icon+" "+f.name+(exists?" (open)":"")),
                    !exists ? React.createElement("div",{style:{display:"flex",gap:2}},
                      SIZE_KEYS.map(function(k){return React.createElement("button",{key:k,onClick:function(){addWin(f.id,k);},style:{background:t.bgAlt,border:"1px solid "+t.border,color:t.muted,padding:"1px 4px",fontSize:6,cursor:"pointer",fontFamily:"inherit"}},SIZES[k].l);})
                    ) : null
                  );
                })
              );})
            ) : null
          ),
          React.createElement("span", {style:{color:t.muted,fontSize:7}}, "\u2502 "+active.length+" open \u00B7 "+minimized.length+" min"),
          React.createElement("span", {style:{marginLeft:"auto",color:t.muted,fontSize:7}}, now.toLocaleDateString())
        ),

        /* Window Grid */
        React.createElement("div", {style:{flex:1,overflow:"auto",padding:5}},
          React.createElement("div", {style:{display:"grid",gridTemplateColumns:"1fr 1fr",gridAutoRows:"minmax(200px,1fr)",gap:5}},
            active.map(function(win){
              var sp = SIZES[win.size];
              var Comp = RMAP[win.fid];
              return React.createElement("div", {key:win.wid, style:{gridColumn:sp.gc,gridRow:sp.gr,border:"1px solid "+t.border,background:t.bgWin,display:"flex",flexDirection:"column",overflow:"hidden",transition:"all .2s"}},
                /* titlebar */
                React.createElement("div", {style:{display:"flex",alignItems:"center",padding:"2px 5px",background:t.bgAlt,borderBottom:"1px solid "+t.border,flexShrink:0,gap:3}},
                  React.createElement("span", {style:{color:t.accent,fontSize:9}}, win.icon),
                  React.createElement("span", {style:{color:t.accent,fontSize:8,fontWeight:700,flex:1,overflow:"hidden",textOverflow:"ellipsis",whiteSpace:"nowrap"}}, win.name),
                  React.createElement("div", {style:{display:"flex",gap:1}},
                    SIZE_KEYS.map(function(k){return React.createElement("button",{key:k,onClick:function(){setSz(win.wid,k);},style:{background:win.size===k?t.accent+"30":"transparent",border:"1px solid "+(win.size===k?t.accent:t.border)+"40",color:win.size===k?t.accent:t.muted,width:16,height:14,cursor:"pointer",fontSize:6,fontFamily:"inherit",display:"flex",alignItems:"center",justifyContent:"center"}},SIZES[k].l);})
                  ),
                  React.createElement("div",{style:{width:1,height:10,background:t.border,margin:"0 1px"}}),
                  React.createElement("button",{onClick:function(){togMin(win.wid);},title:"Minimize",style:{background:"none",border:"1px solid "+t.border+"40",color:t.warn,width:16,height:14,cursor:"pointer",fontSize:9,fontFamily:"inherit",display:"flex",alignItems:"center",justifyContent:"center"}},"\u25BC"),
                  React.createElement("button",{onClick:function(){rmWin(win.wid);},title:"Close",style:{background:"none",border:"1px solid "+t.border+"40",color:t.sell,width:16,height:14,cursor:"pointer",fontSize:9,fontFamily:"inherit",display:"flex",alignItems:"center",justifyContent:"center"}},"\u2715")
                ),
                /* content */
                React.createElement("div", {style:{flex:1,padding:6,overflow:"auto",minHeight:0}},
                  Comp ? React.createElement(Comp, {t:t}) : React.createElement("div",{style:{color:t.muted}},"N/A")
                )
              );
            })
          )
        )
      )
    ),

    /* FOOTER */
    React.createElement("footer", {style:{borderTop:"1px solid "+t.border,padding:"3px 10px",display:"flex",justifyContent:"space-between",background:t.bgPanel,fontSize:7,color:t.muted,flexShrink:0}},
      React.createElement("div", {style:{display:"flex",gap:12}},
        React.createElement("span",null,"\u00A9 2026 SEESAW MFSES"),
        React.createElement("a",{href:"/",style:{color:t.accent,textDecoration:"none"}},"Home"),
        React.createElement("a",{href:"/dashboard",style:{color:t.accent,textDecoration:"none"}},"Dashboard"),
        React.createElement("a",{href:"/learn",style:{color:t.accent,textDecoration:"none"}},"Learn")
      ),
      React.createElement("div", {style:{display:"flex",gap:8,alignItems:"center"}},
        React.createElement("span",null,"SEC \u00B7 Polygon \u00B7 Reuters"),
        React.createElement("span",{style:{color:t.accent}},"\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2591"),
        React.createElement("span",null,"SYS OK")
      )
    ),

    /* STYLES */
    React.createElement("style", null,
      "@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@300;400;500;600;700&display=swap');"+
      "*{box-sizing:border-box;margin:0;padding:0;}"+
      "::-webkit-scrollbar{width:4px;height:4px;}"+
      "::-webkit-scrollbar-track{background:"+t.bg+";}"+
      "::-webkit-scrollbar-thumb{background:"+t.scrollbar+";}"+
      "::-webkit-scrollbar-thumb:hover{background:"+t.accent+";}"+
      "input::placeholder{color:"+t.muted+";opacity:.5;}"+
      "button{transition:all .12s;}button:hover{filter:brightness(1.15);}"
    )
  ));
}
