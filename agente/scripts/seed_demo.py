"""
seed_demo.py — Carga datos de demo realistas para Liados.

NO requiere Gmail/Last.app reales. Inserta:
  - 10 vendors típicos de restauración/bar en España
  - ~30 facturas expense (Coca-Cola, Makro, Endesa, etc.) últimos 90 días
  - ~50 facturas income (ventas TPV) últimos 90 días
  - Pagos asociados a parte de las facturas expense
  - Registros en sync_control y agent_logs

Uso:
    python3 -m agente.scripts.seed_demo                # carga datos
    python3 -m agente.scripts.seed_demo --wipe         # borra todo y carga
    python3 -m agente.scripts.seed_demo --wipe --no-seed  # solo borra
"""
import os
import sys
import random
from datetime import date, timedelta
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from agente.scripts.db_connection import get_conn

random.seed(20260610)

VENDORS_EXPENSE = [
    ("Coca-Cola Europacific Partners",  "A-15008778",     "Suministros",            "cocacolaep.com"),
    ("Makro Autoservicio Mayorista SA", "A-08133150",     "Suministros",            "makro.es"),
    ("Endesa Energía SAU",              "A-81948077",     "Suministros",            "endesa.com"),
    ("Telefónica de España SAU",        "A-28015865",     "Telecomunicaciones",     "telefonica.com"),
    ("Seguros Catalana Occidente",       "A-08168213",     "Seguros",                "seguroscatalanaoccidente.com"),
    ("Limpiezas Brillante SL",          "B-12345678",     "Servicios Profesionales","brillante.es"),
    ("Distribuciones García SL",        "B-87654321",     "Suministros",            "distribucionesgarcia.es"),
    ("Ayuntamiento de Madrid",          "P-2807900-B",    "Impuestos y Tasas",      "madrid.es"),
    ("HBAL Holding de Bebidas SL",      "B-11223344",     "Suministros",            "hbal.es"),
    ("Cervezas Mahou SA",               "A-28076234",     "Suministros",            "mahou.es"),
]

SALES_LOCATIONS = [
    ("Liados Centro",     "L-001"),
    ("Liados Malasaña",   "L-002"),
    ("Liados La Latina",  "L-003"),
    ("Liados Chueca",     "L-004"),
]


def _q(d):
    if isinstance(d, Decimal):
        return d
    if d is None:
        return Decimal("0")
    return Decimal(str(d))


# Whitelist de tablas permitidas para el wipe (anti SQL-injection en f-string)
WIPE_TABLES = ("agent_logs", "user_overrides", "orphan_payments",
               "invoices", "vendors", "categories", "sync_control")


def wipe(cur):
    print("Wipe de tablas...")
    for tbl in WIPE_TABLES:
        # Whitelist: si tbl no está en la lista, abortar
        if tbl not in WIPE_TABLES:
            raise ValueError(f"Tabla no permitida para wipe: {tbl}")
        cur.execute(f"DELETE FROM {tbl};")
    cur.execute("""
        INSERT INTO categories (name, icon, color) VALUES
            ('Software y SaaS', null, '#3B82F6'),
            ('Oficina', null, '#10B981'),
            ('Viajes y Transporte', null, '#F59E0B'),
            ('Marketing y Publicidad', null, '#EF4444'),
            ('Servicios Profesionales', null, '#8B5CF6'),
            ('Suministros', null, '#06B6D4'),
            ('Seguros', null, '#6366F1'),
            ('Alquiler', null, '#EC4899'),
            ('Telecomunicaciones', null, '#14B8A6'),
            ('Gastos Bancarios', null, '#F97316'),
            ('Impuestos y Tasas', null, '#78716C'),
            ('Restauración y Hostelería', null, '#EAB308'),
            ('Otros', null, '#A8A29E')
        ON CONFLICT (name) DO NOTHING;
    """)
    cur.execute("INSERT INTO sync_control (source) VALUES ('erp'), ('gmail') "
                "ON CONFLICT DO NOTHING;")


def get_category_id(cur, name):
    cur.execute("SELECT id FROM categories WHERE name = %s;", (name,))
    row = cur.fetchone()
    if not row:
        raise RuntimeError(f"Categoria no encontrada: {name}")
    return row[0]


def get_or_create_vendor(cur, name, tax_id, email, category_id):
    cur.execute("SELECT id FROM vendors WHERE name = %s AND tax_id = %s;",
                (name, tax_id))
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute("""
        INSERT INTO vendors (name, tax_id, email, default_category_id, is_active)
        VALUES (%s, %s, %s, %s, true)
        RETURNING id;
    """, (name, tax_id, email, category_id))
    row = cur.fetchone()
    return row[0]


def insert_expense_invoices(cur, days_back=90):
    today = date.today()
    inserted = 0
    seq = 1000
    for name, tax_id, category_name, email_domain in VENDORS_EXPENSE:
        category_id = get_category_id(cur, category_name)
        vendor_id = get_or_create_vendor(
            cur, name, tax_id, f"facturas@{email_domain}", category_id
        )
        n = random.randint(1, 4)
        for i in range(n):
            inv_date = today - timedelta(days=random.randint(1, days_back))
            if category_name == "Suministros":
                base = random.uniform(180, 1800)
            elif category_name == "Servicios Profesionales":
                base = random.uniform(400, 2200)
            elif category_name == "Telecomunicaciones":
                base = random.uniform(60, 280)
            elif category_name == "Seguros":
                base = random.uniform(800, 3500)
            elif category_name == "Impuestos y Tasas":
                base = random.uniform(150, 900)
            else:
                base = random.uniform(100, 1500)
            base_d = _q(round(base, 2))
            tax_d = _q(round(base_d * Decimal("0.21"), 2))
            total_d = _q(round(base_d + tax_d, 2))
            seq += 1
            source_account = random.choice(["principal", "secundaria"])
            r = random.random()
            if r < 0.65:
                status = "paid"
            elif r < 0.85:
                status = "classified"
            elif r < 0.95:
                status = "verified"
            else:
                status = "pending"
            try:
                cur.execute("""
                    INSERT INTO invoices (
                        type, source, source_id, source_account,
                        invoice_number, invoice_date, due_date,
                        vendor_id, vendor_name, vendor_tax_id,
                        base_amount, tax_amount, total_amount, currency,
                        category_id, category_raw, description,
                        status, confidence_score, created_at
                    ) VALUES (
                        'expense', 'gmail', %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s, 'EUR',
                        %s, %s, %s,
                        %s, %s, NOW() - (%s || ' days')::interval
                    )
                    ON CONFLICT (source, source_id) DO NOTHING
                    RETURNING id;
                """, (
                    f"demo-{seq}", source_account,
                    f"FC-{seq}", inv_date, inv_date + timedelta(days=30),
                    vendor_id, name, tax_id,
                    base_d, tax_d, total_d,
                    category_id, category_name,
                    f"Factura {name} - {category_name}",
                    status, round(random.uniform(0.78, 0.99), 2),
                    random.randint(1, days_back),
                ))
                row = cur.fetchone()
                if row:
                    inserted += 1
                    inv_id = row[0]
                    # NOTE: la tabla legacy 'payments' fue eliminada (Bloque C plan v5.1.0).
                    # Si se necesita tracking de pagos, usar lastapp_payments en su lugar.
            except Exception as e:
                print(f"  Skip {name}#{seq}: {e}")
    return inserted


def insert_sales_invoices(cur, days_back=90):
    today = date.today()
    inserted = 0
    seq = 5000
    for loc_name, loc_code in SALES_LOCATIONS:
        n_invoices = random.randint(8, 15)
        for i in range(n_invoices):
            inv_date = today - timedelta(days=random.randint(0, days_back))
            base = random.uniform(800, 4500)
            if random.random() < 0.3:
                base_d = _q(round(base / 1.21, 2))
                tax_d = _q(round(base - float(base_d), 2))
                total_d = _q(round(base, 2))
            else:
                base_d = _q(round(base, 2))
                tax_d = _q(0)
                total_d = base_d
            seq += 1
            try:
                cur.execute("""
                    INSERT INTO invoices (
                        type, source, source_id, source_account,
                        invoice_number, invoice_date,
                        vendor_name, vendor_tax_id,
                        base_amount, tax_amount, total_amount, currency,
                        description, status, confidence_score,
                        created_at
                    ) VALUES (
                        'income', 'erp', %s, 'tpv',
                        %s, %s,
                        %s, %s,
                        %s, %s, %s, 'EUR',
                        %s, 'classified', 1.00,
                        %s
                    )
                    ON CONFLICT (source, source_id) DO NOTHING
                    RETURNING id;
                """, (
                    f"demo-sale-{seq}",
                    f"TPV-{loc_code}-{seq}", inv_date,
                    loc_name, "B-LIADOS-2026",
                    base_d, tax_d, total_d,
                    f"Ventas TPV {loc_name} - {inv_date.isoformat()}",
                    inv_date,
                ))
                if cur.fetchone():
                    inserted += 1
            except Exception as e:
                print(f"  Skip sale {loc_name}#{seq}: {e}")
    return inserted


def insert_agent_logs(cur):
    logs = [
        ("gmail_collector", "info", "Sincronizacion Gmail cuenta principal completada", 14),
        ("gmail_collector", "info", "Sincronizacion Gmail cuenta secundaria completada", 7),
        ("lastapp_sync",    "info", "Last.app sync: 23 facturas de venta importadas", 6),
        ("invoice_parser",  "info", "Parser IA proceso 21 adjuntos con exito", 5),
        ("dedup_checker",   "info", "0 duplicados detectados en ultimo batch", 3),
        ("dedup_checker",   "warning", "1 factura con confidence_score < 0.7 requiere revision", 2),
    ]
    for src, lvl, msg, days_ago in logs:
        cur.execute("""
            INSERT INTO agent_logs (source, level, message, details, timestamp)
            VALUES (%s, %s, %s, %s::jsonb, NOW() - (%s || ' days')::interval);
        """, (src, lvl, msg, '{"demo": true, "items": 0}', days_ago))


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Seed de datos demo Liados")
    ap.add_argument("--wipe", action="store_true", help="Borrar datos antes de cargar")
    ap.add_argument("--no-seed", action="store_true", help="Solo wipe, no cargar")
    ap.add_argument("--days", type=int, default=90, help="Dias hacia atras para facturas")
    args = ap.parse_args()
    print("=" * 60)
    print("SEED DEMO - Liados")
    print("=" * 60)
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                if args.wipe:
                    print("\n" + "!" * 60)
                    print("\u26a0\ufe0f  ATENCI\u00d3N: --wipe va a BORRAR TODOS LOS DATOS de las tablas:")
                    print("   invoices, vendors, categories, agent_logs, etc.")
                    print("!" * 60)
                    confirm = input("   Escribe 'BORRAR' para confirmar: ").strip()
                    if confirm != 'BORRAR':
                        print("   Cancelado.")
                        sys.exit(0)
                    print("   Confirmado. Limpiando...")
                    wipe(cur)
                n_expense = 0 if args.no_seed else insert_expense_invoices(cur, args.days)
                n_income = 0 if args.no_seed else insert_sales_invoices(cur, args.days)
                if not args.no_seed:
                    insert_agent_logs(cur)
            conn.commit()
        print()
        print("=" * 60)
        if not args.no_seed:
            print("Seed completo:")
            print(f"   * {n_expense} facturas expense (gastos)")
            print(f"   * {n_income} facturas income (ventas TPV)")
            print(f"   * 6 agent_logs")
            print(f"   * 10 vendors demo")
        else:
            print("Wipe completado (--no-seed)")
        print("=" * 60)
        return 0
    except Exception as e:
        print(f"\nERROR: {e.__class__.__name__}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
