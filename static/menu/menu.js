// Detecta o tenant a partir do path: /m/{tenant}
function getTenantFromPath() {
  const parts = window.location.pathname.split("/").filter(Boolean);
  // Exemplo: ["m", "confeiteira"]
  return parts.length >= 2 ? parts[1] : "confeiteira";
}

const tenant = getTenantFromPath();

// Endpoint público somente-leitura que o backend fornece
const PUBLIC_PRODUCTS_URL = `/m/${encodeURIComponent(tenant)}/products.json`;

// Formata preço em BRL a partir de price_cents (inteiro)
function formatBRLFromCents(cents) {
  const v = Number.isFinite(cents) ? (cents / 100) : 0;
  return v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

// Carrega banner + nome salvos pelo Admin no localStorage (MVP)
function loadBrandingFromLocalStorage() {
  const bannerUrl = localStorage.getItem("branding_banner_url");
  const storeName = localStorage.getItem("branding_store_name") || "Cardápio";
  const storeSubtitle = localStorage.getItem("branding_store_subtitle") || "";

  const titleEl = document.getElementById("storeName");
  const subtitleEl = document.getElementById("storeSubtitle");
  const bannerEl = document.getElementById("banner");

  titleEl.textContent = storeName;
  subtitleEl.textContent = storeSubtitle;

  if (bannerUrl) {
    bannerEl.src = bannerUrl;
    bannerEl.style.display = "block";
  }
}

// Renderiza lista de produtos
function renderProducts(items) {
  const grid = document.getElementById("productGrid");
  grid.innerHTML = "";

  if (!Array.isArray(items) || items.length === 0) {
    const notice = document.getElementById("notice");
    notice.hidden = false;
    notice.textContent = "Nenhum produto disponível no momento.";
    return;
  }

  items.forEach((p) => {
    const card = document.createElement("article");
    card.className = "card";

    const imgHTML = p.image_url
      ? `<img src="${p.image_url}" alt="${(p.name || "Produto")}" loading="lazy" />`
      : `<img alt="Sem imagem" loading="lazy"
           src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='600' height='360'%3E%3Crect width='100%25' height='100%25' fill='%23f3f3f3'/%3E%3Ctext x='50%25' y='50%25' dominant-baseline='middle' text-anchor='middle' fill='%23999' font-family='Arial' font-size='16'%3ESem imagem%3C/text%3E%3C/svg%3E" />`;

    const price = formatBRLFromCents(p.price_cents);

    card.innerHTML = `
      ${imgHTML}
      <div class="content">
        <h3>${p.name || "Produto"}</h3>
        <span class="price">${price}</span>
        <p class="desc">${p.description || ""}</p>
      </div>
    `;

    grid.appendChild(card);
  });
}

// Busca os produtos via endpoint público
async function loadProducts() {
  try {
    const res = await fetch(PUBLIC_PRODUCTS_URL, { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json(); // { items, total }
    renderProducts(data.items || []);
  } catch (err) {
    console.error("Falha ao carregar produtos:", err);
    const notice = document.getElementById("notice");
    notice.hidden = false;
    notice.textContent = "Não foi possível carregar o cardápio agora. Tente novamente em instantes.";
  }
}

// Boot
loadBrandingFromLocalStorage();
loadProducts();