"use strict";

// The four viewer perspectives — the privacy gradient, public -> private.
const VIEWERS = [
  { role: "publicParty", label: "Public",    desc: "the public tape — clearing price & volume only, never a single leg." },
  { role: "regulator",   label: "Regulator", desc: "full per-leg settlement detail — but not anyone's individual holdings." },
  { role: "ownerA",      label: "Owner A",   desc: "your own positions, and the settlements you are a party to." },
  { role: "ownerB",      label: "Owner B",   desc: "your own positions, and the settlements you are a party to." },
];

let current = VIEWERS[0].role;
let flashId = null;          // updateId to highlight after a fresh settlement

// Deep-link: the front end's auction result links here as
//   {EXPLORER_URL}/?party=<role>&tx=<transactionId>
// which selects that viewer and auto-opens that transaction's detail.
const params = new URLSearchParams(location.search);
if (VIEWERS.some((v) => v.role === params.get("party"))) current = params.get("party");
let pendingTx = params.get("tx");

const $ = (id) => document.getElementById(id);

function renderTabs() {
  $("viewers").innerHTML = "";
  for (const v of VIEWERS) {
    const b = document.createElement("button");
    b.textContent = v.label;
    b.className = v.role === current ? "active" : "";
    b.onclick = () => { current = v.role; renderTabs(); load(); };
    $("viewers").appendChild(b);
  }
  const v = VIEWERS.find((x) => x.role === current);
  $("subtitle").innerHTML = `Viewing as <b>${v.label}</b> — ${v.desc}`;
}

function fmtTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleString(undefined, { hour12: false });
}

function summarize(ev) {
  const a = ev.args || {};
  if (ev.template === "Holding:Holding") {
    return ev.kind === "archived"
      ? { text: "− Holding archived", cls: "archived" }
      : { text: `+ ${a.amount} ${a.instrument} → ${a.owner}`, cls: "created" };
  }
  if (ev.template === "Settlement:SettlementRecord")
    return { text: `SettlementRecord · ${(a.legs || []).length} legs`, cls: "rec" };
  if (ev.template === "Settlement:AuctionResult")
    return { text: `AuctionResult · ${a.clearingPrice} USDC/wETH · vol ${a.totalVolume}`, cls: "auc" };
  return { text: `${ev.kind} ${ev.template}`, cls: ev.kind };
}

function renderList(data) {
  const list = $("list");
  list.innerHTML = "";
  if (!data.transactions.length) {
    list.innerHTML = `<div class="empty">No transactions visible to <b>${data.viewer}</b> yet — hit “Run settlement”.</div>`;
    return;
  }
  for (const tx of data.transactions) {
    const row = document.createElement("div");
    row.className = "row" + (tx.updateId === flashId ? " flash" : "");
    const chips = tx.events.map((ev) => {
      const s = summarize(ev);
      return `<span class="chip ${s.cls}">${s.text}</span>`;
    }).join("");
    row.innerHTML = `
      <div class="row-top">
        <span class="uid">${tx.updateId.slice(0, 22)}…</span>
        <span class="when">offset ${tx.offset} · ${fmtTime(tx.time)}</span>
      </div>
      <div class="summary">${chips}</div>`;
    row.onclick = () => openModal(tx);
    list.appendChild(row);
  }
  flashId = null;
}

function kvTable(obj) {
  const rows = Object.entries(obj)
    .filter(([k]) => k !== "legs")
    .map(([k, v]) => `<tr><th>${k}</th><td class="${typeof v === "object" ? "mono" : ""}">${typeof v === "object" ? JSON.stringify(v) : v}</td></tr>`)
    .join("");
  return `<table>${rows}</table>`;
}

function legsTable(legs) {
  const rows = legs.map((l) => {
    const d = parseFloat(l.delta);
    return `<tr><td>${l.party}</td><td>${l.instrument}</td>
      <td class="num ${d < 0 ? "neg" : "pos"}">${d > 0 ? "+" : ""}${l.delta}</td></tr>`;
  }).join("");
  return `<table><tr><th>party</th><th>instrument</th><th class="num">delta</th></tr>${rows}</table>`;
}

function openModal(tx) {
  const events = tx.events.map((ev) => {
    const a = ev.args || {};
    let detail = ev.kind === "archived" ? `<div class="cid">contract ${ev.contractId}</div>` : kvTable(a);
    if (ev.template === "Settlement:SettlementRecord" && a.legs) detail += legsTable(a.legs);
    return `<div class="event">
        <h3><span class="chip ${summarize(ev).cls}">${ev.kind}</span> ${ev.template}</h3>
        ${detail}</div>`;
  }).join("");
  $("modal-body").innerHTML = `
    <h2>Transaction</h2>
    <div class="uid-full">${tx.updateId}</div>
    <div class="when" style="margin:6px 0 4px">offset ${tx.offset} · ${fmtTime(tx.time)}</div>
    ${events}`;
  $("modal").classList.remove("hidden");
}

async function load() {
  try {
    const r = await fetch(`/api/tx?party=${encodeURIComponent(current)}`);
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || "request failed");
    const hit = pendingTx ? data.transactions.find((t) => t.updateId === pendingTx) : null;
    if (hit) flashId = pendingTx;       // highlight the deep-linked row
    renderList(data);
    if (pendingTx) {                    // one-shot: resolve the deep-link, then clear it
      if (hit) openModal(hit);
      else toast(`Transaction ${pendingTx.slice(0, 12)}… not visible to ${data.viewer}`, true);
      pendingTx = null;
    }
  } catch (e) {
    toast(e.message, true);
  }
}

function toast(msg, isErr) {
  const t = $("toast");
  t.textContent = msg;
  t.className = "toast " + (isErr ? "err" : "ok");
  setTimeout(() => t.classList.add("hidden"), 4200);
}

async function runSettlement() {
  const btn = $("run");
  btn.disabled = true;
  btn.textContent = "⏳ Settling…";
  try {
    const r = await fetch("/api/settle", { method: "POST" });
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || "settlement failed");
    flashId = data.updateId;
    toast(`Settled · ${data.updateId.slice(0, 22)}…`, false);
    await load();
  } catch (e) {
    toast(e.message, true);
  } finally {
    btn.disabled = false;
    btn.textContent = "▶ Run settlement";
  }
}

$("run").onclick = runSettlement;
$("modal-close").onclick = () => $("modal").classList.add("hidden");
$("modal").onclick = (e) => { if (e.target.id === "modal") $("modal").classList.add("hidden"); };

renderTabs();
load();
