import{t as e}from"./jsx-runtime-DeQB9eiY.js";
const r=e();
function IconElementRenderer({iconName:e="cpu",size:t=48,color:n="#FFFFFF",strokeWidth:o=2}) {
  const s=String(e||"").toLowerCase();
  const a={width:t,height:t,viewBox:"0 0 24 24",fill:"none",stroke:n,strokeWidth:o,strokeLinecap:"round",strokeLinejoin:"round",style:{display:"block"}};
  if (s.includes("gpu")) return r.jsxs("svg",{...a,children:[
    r.jsx("rect",{x:"3",y:"6",width:"14",height:"10",rx:"2"}),
    r.jsx("path",{d:"M7 10h6v2H7z"}),
    r.jsx("path",{d:"M17 9h3"}),
    r.jsx("path",{d:"M17 13h3"}),
    r.jsx("path",{d:"M6 19h8"})
  ]});
  if (s.includes("fan")) return r.jsxs("svg",{...a,children:[
    r.jsx("circle",{cx:"12",cy:"12",r:"2"}),
    r.jsx("path",{d:"M12 4c3 0 4 3 2 5"}),
    r.jsx("path",{d:"M19 15c-1.5 2.6-4.7 2.4-5.8-.1"}),
    r.jsx("path",{d:"M5 15c-1.5-2.6.1-5.4 2.9-5"})
  ]});
  if (s.includes("temp")||s.includes("therm")) return r.jsxs("svg",{...a,children:[
    r.jsx("path",{d:"M14 14.76V5a2 2 0 0 0-4 0v9.76a4 4 0 1 0 4 0Z"}),
    r.jsx("path",{d:"M12 9v6"})
  ]});
  return r.jsxs("svg",{...a,children:[
    r.jsx("rect",{x:"6",y:"6",width:"12",height:"12",rx:"2"}),
    r.jsx("path",{d:"M9 1v3"}),
    r.jsx("path",{d:"M15 1v3"}),
    r.jsx("path",{d:"M9 20v3"}),
    r.jsx("path",{d:"M15 20v3"}),
    r.jsx("path",{d:"M20 9h3"}),
    r.jsx("path",{d:"M20 15h3"}),
    r.jsx("path",{d:"M1 9h3"}),
    r.jsx("path",{d:"M1 15h3"})
  ]});
}
export{IconElementRenderer};
