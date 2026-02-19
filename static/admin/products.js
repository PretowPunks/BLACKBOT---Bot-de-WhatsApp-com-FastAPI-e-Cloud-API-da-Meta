/* Admin do Cardápio - Allisson (MVP)
 * - Presign PUT → R2
 * - CRUD de produtos
 * - Config por localStorage (com fallback)
 * - Corrigido para backend que retorna { items, total, ... }
 */

const FIXED_TENANT = "confeiteira"; // 🔥 SLUG FIXO DA LOJA

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const cfg = {
  get tenant() { return localStorage.getItem("tenant_slug") || ""; },
  set tenant(v) { localStorage.setItem("tenant_slug", (v || "").trim()); },
  get token() { return localStorage.getItem("admin_token") || ""; },
  set token(v) { localStorage.setItem("admin_token", (v || "").trim()); },
};

// Slug final usado em todas as chamadas:
function getTenant() {
  const raw = cfg.tenant?.trim().toLowerCase();
  return raw || FIXED_TENANT; // fallback seguro
}

function toast(msg, kind = "info", ms = 2400) {
  const el = $("#toast");
  el.textContent = msg;
  el.className = `toast toast--${kind} toast--show`;
  setTimeout(() => (el.className = "toast"), ms);
}

function moneyToCents(input) {
  if (!input) return 0;
  let s = String(input).replace(/[^\d,.-]/g, "");
  if (s.includes(",") && s.includes(".")) {
    s = s.replace(/\./g, "").replace(",", ".");
  } else if (s.includes(",")) {
    s = s.replace(",", ".");
  }
  const num = Number(s);
  return Number.isNaN(num) ? 0 : Math.round(num * 100);
}

function centsToMoneyBR(cents) {
  return (Number(cents || 0) / 100).toLocaleString("pt-BR", {
    style: "currency",
    currency: "BRL",
  });
}

function ensureCfg() {
  $("#tenantSlug").value = cfg.tenant || FIXED_TENANT;
  $("#adminToken").value = cfg.token;
  return Boolean(cfg.token); // tenant vira sempre o fixo
}

// API helper
async function api(path, { method = "GET", body } = {}) {
  const tenant = getTenant();
  const token = cfg.token;
  if (!tenant || !token) throw new Error("Configure o Token Admin primeiro.");

  const url = path.replace(":tenant", encodeURIComponent(tenant));
  const headers = { "X-Admin-Token": token };
  if (body) headers["Content-Type"] = "application/json";

  const res = await fetch(url, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });

  if (!res.ok) {
    let errTxt = "";
    try {
      errTxt = await res.text();
    } catch {}
    throw new Error(`Falha API ${res.status}: ${errTxt}`);
  }

  const ct = res.headers.get("content-type") || "";
  return ct.includes("application/json") ? res.json() : res.text();
}

// Upload para R2
async function presignAndUpload(file) {
  if (!file) return null;

  const presign = await api(`/api/t/:tenant/upload-url`, {
    method: "POST",
    body: {
      filename: file.name,
      content_type: file.type || "application/octet-stream",
      expires_in: 600,
    },
  });

  const { put_url, public_url, content_type } = presign;

  const putRes = await fetch(put_url, {
    method: "PUT",
    headers: {
      "Content-Type": content_type || file.type || "application/octet-stream",
    },
    body: file,
  });

  if (!putRes.ok) {
    const t = await putRes.text().catch(() => "");
    throw new Error(`Falha no upload R2: ${putRes.status} ${t}`);
  }

  return public_url;
}

// ---------- CRUD ----------
async function listProducts() {
  const data = await api(`/api/t/:tenant/products`);
  // 🤩 Backend retorna { items, total, ... }
  renderProducts(data.items || []);
}

async function createProduct() {
  const name = $("#np_name").value.trim();
  const description = $("#np_description").value.trim();
  const sku = $("#np_sku").value.trim();
  const price_cents = moneyToCents($("#np_price").value);
  const file = $("#np_image").files?.[0];

  if (!name) return toast("Informe o nome do produto", "warn");
  if (price_cents <= 0) return toast("Informe um preço válido", "warn");

  $("#btnCreate").disabled = true;
  $("#btnCreate").textContent = "Enviando...";

  try {
    let image_url = null;
    if (file) image_url = await presignAndUpload(file);

    await api(`/api/t/:tenant/products`, {
      method: "POST",
      body: {
        sku: sku || null,
        name,
        description: description || null,
        price_cents,
        currency: "BRL",
        image_url,
      },
    });

    toast("Produto criado!", "success");
    await listProducts();
    resetForm();
  } catch (err) {
    console.error(err);
    toast(err.message, "error", 3600);
  } finally {
    $("#btnCreate").disabled = false;
    $("#btnCreate").textContent = "Criar produto";
  }
}

async function updateProduct(id, fields) {
  await api(`/api/t/:tenant/products/${id}`, {
    method: "PUT",
    body: fields,
  });
}

async function deleteProduct(id) {
  if (!confirm("Tem certeza que deseja remover este produto?")) return;
  await api(`/api/t/:tenant/products/${id}`, { method: "DELETE" });
  toast("Produto removido", "success");
  await listProducts();
}

// ---------- UI ----------
function resetForm() {
  $("#np_name").value = "";
  $("#np_description").value = "";
  $("#np_sku").value = "";
  $("#np_price").value = "";
  $("#np_image").value = "";
  $("#np_preview").style.display = "none";
}

function renderProducts(items) {
  const el = $("#products");
  const empty = $("#emptyState");
  el.innerHTML = "";

  if (!items.length) {
    empty.style.display = "block";
    return;
  }
  empty.style.display = "none";

  for (const p of items) {
    const card = document.createElement("div");
    card.className = "product-card";

    const img = document.createElement("img");
    img.className = "product-card__img";
    img.alt = p.name;
    img.src =
      p.image_url ||
      "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==";

    const body = document.createElement("div");
    body.className = "product-card__body";

    const title = document.createElement("div");
    title.className = "product-card__title";
    title.textContent = p.name || "(sem nome)";

    const price = document.createElement("div");
    price.className = "product-card__price";
    price.textContent = centsToMoneyBR(p.price_cents);

    const desc = document.createElement("div");
    desc.className = "product-card__desc";
    desc.textContent = p.description || "";

    const actions = document.createElement("div");
    actions.className = "product-card__actions";

    const btnEdit = document.createElement("button");
    btnEdit.className = "btn btn--ghost";
    btnEdit.textContent = "Editar";
    btnEdit.onclick = () => openEditor(card, p);

    const btnDel = document.createElement("button");
    btnDel.className = "btn btn--danger";
    btnDel.textContent = "Excluir";
    btnDel.onclick = () => deleteProduct(p.id);

    actions.append(btnEdit, btnDel);
    body.append(title, price, desc, actions);
    card.append(img, body);
    el.append(card);
  }
}

function openEditor(card, p) {
  if (card.querySelector(".editor")) {
    card.querySelector(".editor").remove();
    return;
  }

  const editor = document.createElement("div");
  editor.className = "editor";

  editor.innerHTML = `
    <div class="row">
      <label>Nome</label>
      <input class="ed_name" value="${htmlEscape(p.name || "")}">
    </div>
    <div class="row">
      <label>Descrição</label>
      <textarea class="ed_description">${htmlEscape(
        p.description || ""
      )}</textarea>
    </div>
    <div class="row row--2col">
      <div>
        <label>SKU</label>
        <input class="ed_sku" value="${htmlEscape(p.sku || "")}">
      </div>
      <div>
        <label>Preço (R$)</label>
        <input class="ed_price" value="${(
          Number(p.price_cents) / 100
        ).toLocaleString("pt-BR", { minimumFractionDigits: 2 })}">
      </div>
    </div>
    <div class="row">
      <label>Imagem (substituir)</label>
      <input type="file" class="ed_image" accept="image/*">
    </div>
    <div class="row row--inline">
      <button class="btn btn--ghost ed_cancel">Fechar</button>
      <button class="btn ed_save">Salvar alterações</button>
    </div>
  `;

  editor.querySelector(".ed_cancel").onclick = () => editor.remove();

  editor.querySelector(".ed_save").onclick = async () => {
    const fields = {
      name: editor.querySelector(".ed_name").value.trim(),
      description: editor.querySelector(".ed_description").value.trim() || null,
      sku: editor.querySelector(".ed_sku").value.trim() || null,
      price_cents: moneyToCents(editor.querySelector(".ed_price").value),
      currency: "BRL",
    };

    const imgFile = editor.querySelector(".ed_image").files?.[0];

    if (imgFile) {
      const newUrl = await presignAndUpload(imgFile);
      fields.image_url = newUrl;
    }

    await updateProduct(p.id, fields);
    toast("Produto atualizado!", "success");
    await listProducts();
    editor.remove();
  };

  card.append(editor);
};

function htmlEscape(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

// ---------- Eventos ----------
function bindEvents() {
  $("#btnSaveCfg").onclick = () => {
    cfg.tenant = $("#tenantSlug").value;
    cfg.token = $("#adminToken").value;
    toast("Config salva", "success");
  };

  $("#btnClearCfg").onclick = () => {
  localStorage.removeItem("tenant_slug");
  localStorage.removeItem("admin_token");
  $("#tenantSlug").value = FIXED_TENANT; // mostra o slug fixo no input
  $("#adminToken").value = "";
  toast("Config limpa", "info");
};

  $("#btnRefresh").onclick = () => {
    if (!ensureCfg()) return toast("Configure Token Admin", "warn");
    listProducts().catch((e) => toast(e.message, "error"));
  };

  $("#np_image").addEventListener("change", (e) => {
    const file = e.target.files?.[0];
    const prev = $("#np_preview");
    if (file) {
      const url = URL.createObjectURL(file);
      prev.src = url;
      prev.style.display = "block";
    } else {
      prev.style.display = "none";
    }
  });

  $("#btnCreate").onclick = () => {
    if (!ensureCfg()) return toast("Configure Token Admin", "warn");
    createProduct();
  };

  $("#btnResetForm").onclick = resetForm;
}

// ---------- Init ----------
(function init() {
  ensureCfg();
  bindEvents();

  if (cfg.token) {
    listProducts().catch(() => {});
  }

  // Mostra o tenant fixo na UI
  $("#tenantSlug").value = FIXED_TENANT;
})();