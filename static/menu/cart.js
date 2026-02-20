(function () {
  const [ , m, tenant ] = window.location.pathname.split("/");
  const CART_KEY = `bb_cart_${tenant}`;

  // Branding
  const brandName = localStorage.getItem("bb_brand_name") || tenant || "Loja";
  const bannerUrl = localStorage.getItem("bb_banner_url") || "";
  const brandNameEl = document.getElementById("brandName");
  const brandBannerEl = document.getElementById("brandBanner");
  if (brandNameEl) brandNameEl.textContent = brandName;
  if (brandBannerEl && bannerUrl) {
    brandBannerEl.src = bannerUrl;
    brandBannerEl.style.display = "block";
  }

  // Elements
  const cartEmpty = document.getElementById("cartEmpty");
  const cartSection = document.getElementById("cartSection");
  const listEl = document.getElementById("cartList");
  const subtotalEl = document.getElementById("subtotal");
  const totalEl = document.getElementById("total");
  const sendBtn = document.getElementById("sendWhatsAppBtn");
  const catalogBtn = document.getElementById("catalogBtn");

  catalogBtn.href = `/m/${tenant}`;

  function getCart() {
    try { const v = JSON.parse(localStorage.getItem(CART_KEY) || "[]"); return Array.isArray(v) ? v : []; }
    catch { return []; }
  }
  function setCart(items) {
    localStorage.setItem(CART_KEY, JSON.stringify(items));
    render();
  }

  function centsToBRL(cents) {
    return (Number(cents || 0) / 100).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
  }

  function computeTotals(items) {
    const subtotalCents = items.reduce((acc, it) => acc + Number(it.price_cents || 0) * Number(it.qty || 0), 0);
    return { subtotalCents, totalCents: subtotalCents }; // sem frete no MVP
  }

  function itemRow(it, index) {
    const row = document.createElement("div");
    row.className = "cart-item";
    row.innerHTML = `
      <img src="${it.image_url || ""}" alt="${it.name || "Produto"}" />
      <div class="info">
        <h3>${it.name || "Produto"}</h3>
        <div class="meta">SKU: ${it.sku || "-"}</div>
        <div class="qty" style="margin-top:8px;">
          <button class="dec" data-index="${index}" aria-label="Diminuir">−</button>
          <input class="qty-input" data-index="${index}" type="number" min="1" value="${it.qty || 1}" inputmode="numeric" />
          <button class="inc" data-index="${index}" aria-label="Aumentar">+</button>
        </div>
      </div>
      <div class="aside">
        <div class="price">${centsToBRL((it.price_cents || 0) * (it.qty || 1))}</div>
        <button class="remove-btn" data-index="${index}">Remover</button>
      </div>
    `;
    return row;
  }

  function updateWhatsAppLink(items) {
    const phone = (localStorage.getItem("bb_whatsapp_phone") || "").replace(/\D/g, "");
    if (!items.length) {
      sendBtn.href = "#";
      sendBtn.setAttribute("aria-disabled", "true");
      sendBtn.style.pointerEvents = "none";
      return;
    }
    const { subtotalCents, totalCents } = computeTotals(items);

    const lines = [
      `Olá! Gostaria de fazer um pedido:`,
      ...items.map(it => {
        const unit = centsToBRL(it.price_cents);
        const sub = centsToBRL((it.price_cents || 0) * (it.qty || 1));
        return `- ${it.qty}x ${it.name} (${unit}) — ${sub}`;
      }),
      `Total: ${centsToBRL(totalCents)}`,
      `Loja: ${brandName}`,
      `Catálogo: ${location.origin}/m/${tenant}`
    ];
    const text = encodeURIComponent(lines.join("\n"));
    sendBtn.removeAttribute("aria-disabled");
    sendBtn.style.pointerEvents = "auto";
    sendBtn.href = phone ? `https://wa.me/${phone}?text=${text}` : `https://wa.me/?text=${text}`;
  }

  function render() {
    const items = getCart();

    if (!items.length) {
      cartEmpty.classList.remove("hidden");
      cartSection.classList.add("hidden");
      return;
    }

    cartEmpty.classList.add("hidden");
    cartSection.classList.remove("hidden");

    listEl.innerHTML = "";
    items.forEach((it, idx) => listEl.appendChild(itemRow(it, idx)));

    const { subtotalCents, totalCents } = computeTotals(items);
    subtotalEl.textContent = centsToBRL(subtotalCents);
    totalEl.textContent = centsToBRL(totalCents);

    updateWhatsAppLink(items);
  }

  // Eventos (delegação)
  document.addEventListener("click", (ev) => {
    const dec = ev.target.closest(".dec");
    const inc = ev.target.closest(".inc");
    const rm = ev.target.closest(".remove-btn");
    if (!dec && !inc && !rm) return;

    const items = getCart();
    if (dec || inc) {
      const i = Number((dec || inc).dataset.index);
      if (Number.isFinite(i) && items[i]) {
        const delta = inc ? 1 : -1;
        items[i].qty = Math.max(1, Number(items[i].qty || 1) + delta);
      }
      setCart(items);
    } else if (rm) {
      const i = Number(rm.dataset.index);
      if (Number.isFinite(i)) {
        items.splice(i, 1);
        setCart(items);
      }
    }
  });

  document.addEventListener("input", (ev) => {
    const input = ev.target.closest(".qty-input");
    if (!input) return;
    const i = Number(input.dataset.index);
    const items = getCart();
    if (Number.isFinite(i) && items[i]) {
      const q = Math.max(1, parseInt(input.value || "1", 10));
      items[i].qty = q;
      setCart(items);
    }
  });

  render();
})();