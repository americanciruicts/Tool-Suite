import sys
sys.path.append('api')
from excel_tool import compare_boms

print("Debugging key generation...")
try:
    # Set debug mode
    import os
    os.environ['DEBUG_VERBOSE'] = 'true'
    
    results = compare_boms('test_files/motherboard BOM.xls', 'test_files/MIRO CUBE GEN2 ENT Motherboard REV07A.xls')
    print(f"\nResults:")
    print(f"Removed parts: {len(results['removed_parts'])}")
    print(f"New parts: {len(results['new_parts'])}")
    print(f"Modified parts: {len(results['modified_parts'])}")
    
    print("\nRemoved parts:")
    for part in results['removed_parts']:
        print(f"  - {part['MPN']}")
        
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
