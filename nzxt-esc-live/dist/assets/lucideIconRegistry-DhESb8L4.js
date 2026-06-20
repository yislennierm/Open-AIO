const n=["cpu","gpu","fan","monitor","thermometer","gauge","zap","settings","wifi","wrench"];
function t(e){return n.includes(String(e||"").toLowerCase())?String(e).toLowerCase():"monitor"}
export{n as L,n as lucideIconNames,t as normalizeLucideIconName};
