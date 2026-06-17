#!/usr/bin/env python3
"""
storage_status.py — Muestra el estado del almacenamiento de facturas
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))

from storage import get_storage_stats, RAW_DIR, PROCESSED_DIR, TEMP_DIR

def main():
    print("=" * 60)
    print("ESTADO DEL ALMACENAMIENTO DE FACTURAS")
    print("=" * 60)
    print()
    
    print("📁 Directorios:")
    print(f"   Raw:       {RAW_DIR}")
    print(f"   Processed: {PROCESSED_DIR}")
    print(f"   Temp:      {TEMP_DIR}")
    print()
    
    stats = get_storage_stats()
    
    print("📊 Estadísticas:")
    print(f"   Archivos raw:       {stats['raw_files']:>6} ({stats['raw_size_mb']:.2f} MB)")
    print(f"   Archivos processed: {stats['processed_files']:>6} ({stats['processed_size_mb']:.2f} MB)")
    print(f"   Archivos temp:      {stats['temp_files']:>6} ({stats['temp_size_mb']:.2f} MB)")
    print()
    
    total_files = stats['raw_files'] + stats['processed_files'] + stats['temp_files']
    total_size = stats['raw_size_mb'] + stats['processed_size_mb'] + stats['temp_size_mb']
    
    print(f"   TOTAL:              {total_files:>6} ({total_size:.2f} MB)")
    print()
    print("=" * 60)

if __name__ == '__main__':
    main()
