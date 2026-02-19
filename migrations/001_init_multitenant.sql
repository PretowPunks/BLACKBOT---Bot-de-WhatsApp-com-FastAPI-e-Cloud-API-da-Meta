-- Tenants
CREATE TABLE IF NOT EXISTS tenants (
  id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
  slug TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Credenciais WhatsApp por tenant
CREATE TABLE IF NOT EXISTS tenant_secrets (
  id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
  tenant_id INTEGER NOT NULL,
  wa_phone_number_id TEXT NOT NULL,
  graph_version TEXT NOT NULL DEFAULT 'v22.0',
  wa_access_token_encrypted TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  rotated_at TIMESTAMP,
  CONSTRAINT fk_tenant_secrets FOREIGN KEY (tenant_id) REFERENCES tenants(id)
);

-- Admin tokens por tenant
CREATE TABLE IF NOT EXISTS tenant_admin_tokens (
  id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
  tenant_id INTEGER NOT NULL,
  token_hash TEXT NOT NULL,
  label TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  revoked_at TIMESTAMP,
  UNIQUE (tenant_id, token_hash),
  CONSTRAINT fk_tenant_admin FOREIGN KEY (tenant_id) REFERENCES tenants(id)
);

-- Produtos
CREATE TABLE IF NOT EXISTS products (
  id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
  tenant_id INTEGER NOT NULL,
  sku TEXT,
  name TEXT NOT NULL,
  description TEXT,
  price_cents INTEGER NOT NULL DEFAULT 0,
  currency TEXT NOT NULL DEFAULT 'BRL',
  image_url TEXT,
  category TEXT,
  active INTEGER NOT NULL DEFAULT 1,
  sort_order INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (tenant_id, sku),
  CONSTRAINT fk_products_tenant FOREIGN KEY (tenant_id) REFERENCES tenants(id)
);

-- Itens de pedido
CREATE TABLE IF NOT EXISTS order_items (
  id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
  order_id INTEGER NOT NULL,
  product_id INTEGER,
  qty INTEGER NOT NULL,
  unit_price_cents INTEGER NOT NULL,
  name_snapshot TEXT,
  meta_json TEXT,
  CONSTRAINT fk_items_order FOREIGN KEY (order_id) REFERENCES orders(id),
  CONSTRAINT fk_items_product FOREIGN KEY (product_id) REFERENCES products(id)
);

-- ALTER TABLE nas tabelas existentes (ignore erros se coluna já existir)
-- sessions
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS tenant_id INTEGER;
CREATE INDEX IF NOT EXISTS idx_sessions_tenant_wa ON sessions(tenant_id, wa_id);

-- orders
ALTER TABLE orders ADD COLUMN IF NOT EXISTS tenant_id INTEGER;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS total_cents INTEGER;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS currency TEXT DEFAULT 'BRL';
ALTER TABLE orders ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP;

-- outbox
ALTER TABLE outbox ADD COLUMN IF NOT EXISTS tenant_id INTEGER;

-- processed_messages
ALTER TABLE processed_messages ADD COLUMN IF NOT EXISTS tenant_id INTEGER;

-- messages
ALTER TABLE messages ADD COLUMN IF NOT EXISTS tenant_id INTEGER;
CREATE INDEX IF NOT EXISTS idx_messages_tenant_wa ON messages(tenant_id, wa_id);