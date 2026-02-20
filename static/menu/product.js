(function () {
  const path = window.location.pathname.split("/"); // ["", "m", "{tenant}", "{id}"]
  const tenant = path[2];
  const productId = parseInt(path[3], 10);

  // Branding (MVP pelo localStorage)
  const brandNameEl = document.getElementById("brandName");
  const brandBannerEl = document.getElementById("brandBanner");

  const brandName = localStorage.getItem("bb_brand_name") || tenant;
  const bannerUrl = localStorage.getItem("bb_banner_url") || "";
  brandNameEl.textContent = brandName;
  if (bannerUrl) {
    brandBannerEl.src = bannerUrl;
    brandBannerEl.style.display = "block";
  }

  // Voltar ao cardápio
  const backLink = document.getElementById("backLink");
  backLink.href = `/m/${tenant}`;

  const productSection = document.getElementById("productSection");
  const notFound = document.getElementById("notFound");

  const el = {
    image: document.getElementById("productImage"),
    name: document.getElementById("productName"),
    desc: document.getElementById("productDescription"),
    price: document.getElementById("productPrice"),
    sku: document.getElementById("productSku"),
    qty: document.getElementById("qty"),
    wa: document.getElementById("whatsappBtn"),
  };

  function centsToBRL(cents) {
    const v = (Number(cents || 0) / 100);
    return v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
  }

  function getWhatsAppHref(product, qty) {
    const rawPhone = (localStorage.getItem("bb_whatsapp_phone") || "").replace(/\D/g, "");
    const unit = Number(product.price_cents || 0) / 100;
    const total = (unit * qty).toFixed(2);

    const brand = localStorage.getItem("bb_brand_name") || tenant;
    const lines = [
      `Olá! Gostaria de pedir *${product.name}*`,
      product.sku ? `(SKU: ${product.sku})` : "",
      `Quantidade: ${qty}`,
      `Preço unitário: ${unit.toLocaleString("pt-BR", { style: "currency", currency: "BRL" })}`,
      `Total: ${Number(total).toLocaleString("pt-BR", { style: "currency", currency: "BRL" })}`,
      `Loja: ${brand}`,
    ].filter(Boolean);

    const text = encodeURIComponent(lines.join("\n"));
    return rawPhone ? `https://wa.me/${rawPhone}?text=${text}` : `https://wa.me/?text=${text}`;
  }

  function hydrateProduct(p) {
    document.title = `${p.name} — ${brandName}`;
    if (p.image_url) {
      el.image.src = p.image_url;
      el.image.alt = p.name;
    }
    el.name.textContent = p.name || "Produto";
    el.desc.textContent = p.description || "";
    el.price.textContent = centsToBRL(p.price_cents);
    el.sku.textContent = p.sku ? `SKU: ${p.sku}` : "";
    el.wa.href = getWhatsAppHref(p, parseInt(el.qty.value || "1", 10));
    el.qty.addEventListener("input", () => {
      const q = Math.max(1, parseInt(el.qty.value || "1", 10));
      el.qty.value = String(q);
      el.wa.href = getWhatsAppHref(p, q);
    });
  }

  async function load() {
    if (!tenant || !Number.isFinite(productId)) {
      productSection.classList.add("hidden");
      notFound.classList.remove("hidden");
      return;
    }

    try {
      const res = await fetch(`/m/${tenant}/products.json`, { cache: "no-store" });
      if (!res.ok) throw new Error("Falha ao carregar products.json");
      const data = await res.json();
      const items = Array.isArray(data?.items) ? data.items : [];
      const prod = items.find((it) => Number(it?.id) === productId && it?.tenant_slug === tenant) || null;

      if (!prod) {
        productSection.classList.add("hidden");
        notFound.classList.remove("hidden");
        return;
      }
      hydrateProduct(prod);
    } catch (err) {
      console.error(err);
      productSection.classList.add("hidden");
      notFound.classList.remove("hidden");
    }
  }

  load();
})();
