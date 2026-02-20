(function () {
  // --- Helpers de rota/tenant ---
  const [ , m, tenant ] = window.location.pathname.split("/"); // ["", "m", "{tenant}"]
  if (m !== "m" || !tenant) {
    console.warn("Tenant não detectado na URL. Esperado: /m/{tenant}");
  }

  // --- Branding (MVP pelo localStorage) ---
  const brandName = localStorage.getItem("bb_brand_name") || tenant || "Loja";
  const bannerUrl = localStorage.getItem("bb_banner_url") || "";

  // Tente popular elementos existentes:
  const brandNameEl = document.getElementById("brandName");
  const brandBannerEl = document.getElementById("brandBanner");
  if (brandNameEl) brandNameEl.textContent = brandName;
  if (brandBannerEl && bannerUrl) {
    brandBannerEl.src = bannerUrl;
    brandBannerEl.style.display = "block";
  }

  // --- Botão flutuante do carrinho ---
  const floatingBtn = document.getElementById("floatingCartBtn");
  const cartCountEl = document.getElementById("cartCount");
  if (floatingBtn) {
    floatingBtn.href = `/m/${tenant}/cart`;
  }

  // --- Container de produtos ---
  let grid = document.getElementById("productsGrid");
  if (!grid) {
    // Se não existir, cria um abaixo do banner
    const container = document.querySelector(".container") || document.body;
    grid = document.createElement("div");
    grid.id = "productsGrid";
    grid.className = "products";
    container.appendChild(grid);
  }

  // --- Carrinho (localStorage por tenant) ---
  const CART_KEY = `bb_cart_${tenant}`;
  function getCart() {
    try {
      const v = JSON.parse(localStorage.getItem(CART_KEY) || "[]");
      if (Array.isArray(v)) return v;
      return [];
    } catch { return []; }
  }
  function setCart(items) {
    localStorage.setItem(CART_KEY, JSON.stringify(items));
    updateCartCount();
  }
  function updateCartCount() {
    const items = getCart();
    const count = items.reduce((acc, it) => acc + Number(it.qty || 0), 0);
    if (cartCountEl) cartCountEl.textContent = String(count);
  }
  function addToCart(product) {
    const items = getCart();
    const idx = items.findIndex((it) => Number(it.id) === Number(product.id));
    if (idx >= 0) {
      items[idx].qty = Number(items[idx].qty || 0) + 1;
    } else {
      items.push({
        id: product.id,
        name: product.name,
        price_cents: product.price_cents,
        image_url: product.image_url || "",
        sku: product.sku || "",
        qty: 1,
      });
    }
    setCart(items);
  }

  function centsToBRL(cents) {
    return (Number(cents || 0) / 100)
      .toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
  }

  // --- Render dos cards ---
  function renderProducts(items) {
    grid.innerHTML = "";
    if (!Array.isArray(items) || items.length === 0) {
      grid.innerHTML = `<div style="color:#94a3b8">Nenhum produto disponível no momento.</div>`;
      return;
    }

    const frag = document.createDocumentFragment();
    items.forEach((p) => {
      // Apenas os do tenant correto (defensivo)
      if (p.tenant_slug && p.tenant_slug !== tenant) return;

      const card = document.createElement("div");
      card.className = "product-card";
      card.innerHTML = `
        <img src="${p.image_url || ""}" alt="${p.name || "Produto"}" />
        <div class="product-info">
          <h3>${p.name || "Produto"}</h3>
          <p class="desc">${p.description || ""}</p>
          <div class="product-meta">
            <span class="product-price">${centsToBRL(p.price_cents)}</span>
            <button class="add-btn" data-id="${p.id}">+ Adicionar ao carrinho</button>
          </div>
        </div>
      `;
      frag.appendChild(card);
    });
    grid.appendChild(frag);

    grid.addEventListener("click", (ev) => {
      const btn = ev.target.closest(".add-btn");
      if (!btn) return;
      const id = Number(btn.dataset.id);
      const p = items.find((x) => Number(x.id) === id);
      if (!p) return;
      addToCart(p);
      // Feedback básico
      const prev = btn.textContent;
      btn.textContent = "Adicionado!";
      setTimeout(() => (btn.textContent = prev), 900);
    });
  }

  // --- Boot ---
  async function load() {
    try {
      updateCartCount();
      const res = await fetch(`/m/${tenant}/products.json`, { cache: "no-store" });
      if (!res.ok) throw new Error("Falha ao carregar products.json");
      const data = await res.json();
      const items = Array.isArray(data?.items) ? data.items : [];
      renderProducts(items);
    } catch (e) {
      console.error(e);
      grid.innerHTML = `<div style="color:#ef4444">Erro ao carregar o cardápio.</div>`;
    }
  }

  load();
})();