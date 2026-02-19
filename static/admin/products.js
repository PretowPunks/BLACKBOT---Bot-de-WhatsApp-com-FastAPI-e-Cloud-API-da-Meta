/* Admin do Cardápio - Allisson (MVP)
 * - Presign PUT -> R2
 * - CRUD de produtos
 * - Config por localStorage
 */

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const cfg = {
  get tenant() { return localStorage.getItem("tenant_slug") || ""; },
  set tenant(v) { localStorage.setItem("tenant_slug", (v || "").trim()); },
  get token() { return localStorage.getItem("admin_token") || ""; },
  set token(v) { localStorage.setItem("admin_token", (v || "").trim()); },
};

function toast(msg, kind = "info", ms = 2400) {
  const el = $("#toast");
  el.textContent = msg;
  el.className = `toast toast--${kind} toast--show`;
  setTimeout(() => el.className = "toast", ms);
}

function moneyToCents(input) {
  // Aceita "12,34", "12.34", "R$ 12,34", etc.
  if (!input) return 0;
  let s = String(input).replace(/[^\d,.-]/g, "");
  // Se tiver vírgula e ponto, prioriza última vírgula como decimal
  if (s.includes(",") && s.includes(".")) {
    s = s.replace(/\./g, "").replace(",", ".");
  } else if (s.includes(",")) {
    s = s.replace(",", ".");
  }
  const num = Number(s);
  if (Number.isNaN(num)) return 0;
  return Math.round(num * 100);
}

function centsToMoneyBR(cents) {
  const v = (Number(cents || 0) / 100);
  return v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

function ensureCfg() {
  const t = cfg.tenant;
  const k = cfg.token;
  $("#tenantSlug").value = t;
  $("#adminToken").value = k;
  return Boolean(t && k);
}

async function api(path, { method = "GET", body } = {}) {
  const tenant = cfg.tenant;
  const token = cfg.token;
  if (!tenant || !token) throw new Error("Configure Tenant Slug e X-Admin-Token primeiro.");
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
    try { errTxt = await res.text(); } catch {}
    throw new Error(`Falha API ${res.status}: ${errTxt}`);
  }
  const ct = res.headers.get("content-type") || "";
  if (ct.includes("application/json")) return res.json();
  return res.text();
}

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

  // PUT direto no R2
  const putRes = await fetch(put_url, {
    method: "PUT",
    headers: { "Content-Type": content_type || file.type || "application/octet-stream" },
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
  // Espera uma lista de objetos com {id, sku, name, description, price_cents, currency, image_url}
  renderProducts(Array.isArray(data) ? data : []);
}

async function createProduct() {
  const name = $("#np_name").value.trim();
  const description = $("#np_description").value.trim();
  const sku = $("#np_sku").value.trim();
  const price_cents = moneyToCents($("#np_price").value);
  const file = $("#np_image").files?.[0];

  if (!name) { toast("Informe o nome do produto", "warn"); return; }
  if (price_cents <= 0) { toast("Informe um preço válido", "warn"); return; }

  $("#btnCreate").disabled = true;
  $("#btnCreate").textContent = "Enviando...";

  try {
    let image_url = undefined;
    if (file) {
      image_url = await presignAndUpload(file);
    }

    await api(`/api/t/:tenant/products`, {
      method: "POST",
      body: {
        sku: sku || null,
        name,
        description: description || null,
        price_cents,
        currency: "BRL",
        image_url: image_url || null,
      },
    });
    toast("Produto criado!", "success");
    await listProducts();
    resetForm();
  } catch (err) {
    console.error(err);
    toast(err.message || "Erro ao criar produto", "error", 3600);
  } finally {
    $("#btnCreate").disabled = false;
    $("#btnCreate").textContent = "Criar produto";
  }
}

async function updateProduct(id, fields) {
  await api(`/api/t/:tenant/products/${encodeURIComponent(id)}`, {
    method: "PUT",
    body: fields,
  });
}

async function deleteProduct(id) {
  if (!confirm("Tem certeza que deseja remover este produto?")) return;
  await api(`/api/t/:tenant/products/${encodeURIComponent(id)}`, { method: "DELETE" });
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
    img.alt = p.name || "";
    img.src = p.image_url || "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==";

    const body = document.createElement("div");
    body.className = "product-card__body";

    const title = document.createElement("div");
    title.className = "product-card__title";
    title.textContent = p.name || "(sem nome)";

    const price = document.createElement("div");
    price.className = "product-card__price";
    price.textContent = centsToMoneyBR(p.price_cents || 0);

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
  // Evitar abrir duplicado
  if (card.querySelector(".editor")) {
    const ex = card.querySelector(".editor");
    ex.remove();
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
      <textarea class="ed_description">${htmlEscape(p.description || "")}</textarea>
    </div>
    <div class="row row--2col">
      <div>
        <label>SKU</label>
        <input class="ed_sku" value="${htmlEscape(p.sku || "")}">
      </div>
      <div>
        <label>Preço (R$)</label>
        <input class="ed_price" value="${(Number(p.price_cents || 0) / 100).toLocaleString('pt-BR', { minimumFractionDigits: 2 })}">
      </div>
    </div>
    <div class="row">
      <label>Imagem (substituir)</label>
      <input type="file" class="ed_image" accept="image/*"/>
    </div>
    <div class="row row--inline">
      <button class="btn btn--ghost ed_cancel">Fechar</button>
      <button class="btn ed_save">Salvar alterações</button>
    </div>
  `;

  const btnCancel = editor.querySelector(".ed_cancel");
  const btnSave = editor.querySelector(".ed_save");

  btnCancel.onclick = () => editor.remove();
  btnSave.onclick = async () => {
    const fields = {};
    const name = editor.querySelector(".ed_name").value.trim();
    const description = editor.querySelector(".ed_description").value.trim();
    const sku = editor.querySelector(".ed_sku").value.trim();
    const price = editor.querySelector(".ed_price").value;

    if (!name) { toast("Nome é obrigatório", "warn"); return; }
    fields.name = name;
    fields.description = description || null;
    fields.sku = sku || null;
    fields.price_cents = moneyToCents(price);
    fields.currency = "BRL";

    const imgFile = editor.querySelector(".ed_image").files?.[0];
    if (imgFile) {
      try {
        const newUrl = await presignAndUpload(imgFile);
        fields.image_url = newUrl;
      } catch (e) {
        console.error(e);
        toast(e.message || "Falha ao subir imagem", "error");
        return;
      }
    }

    try {
      await updateProduct(p.id, fields);
      toast("Produto atualizado", "success");
      await listProducts();
      editor.remove();
    } catch (e) {
      console.error(e);
      toast(e.message || "Erro ao atualizar", "error");
    }
  };

  card.append(editor);
}

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
    $("#tenantSlug").value = "";
    $("#adminToken").value = "";
    toast("Config limpa", "info");
  };

  $("#btnRefresh").onclick = () => {
    if (!ensureCfg()) { toast("Configure Tenant e Token", "warn"); return; }
    listProducts().catch(e => toast(e.message || "Falha ao listar", "error"));
  };

  $("#np_image").addEventListener("change", (e) => {
    const file = e.target.files?.[0];
    const prev = $("#np_preview");
    if (file) {
      const url = URL.createObjectURL(file);
      prev.src = url; prev.style.display = "block";
    } else {
      prev.style.display = "none";
    }
  });

  $("#btnCreate").onclick = () => {
    if (!ensureCfg()) { toast("Configure Tenant e Token", "warn"); return; }
    createProduct();
  };

  $("#btnResetForm").onclick = resetForm;
}

// ---------- Init ----------
(function init() {
  ensureCfg();
  bindEvents();
  // Tenta listar na primeira carga se já tiver config
  if (cfg.tenant && cfg.token) listProducts().catch(() => {});
})();