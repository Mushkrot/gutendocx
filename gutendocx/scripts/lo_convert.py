
import uno
import sys
import time
import os
from com.sun.star.beans import PropertyValue

def wait_for_socket(host, port, retries=30, sleep_time=1):
    """Wait for the LibreOffice socket to become available."""
    localContext = uno.getComponentContext()
    resolver = localContext.ServiceManager.createInstanceWithContext(
        "com.sun.star.bridge.UnoUrlResolver", localContext
    )
    
    connection_str = f"uno:socket,host={host},port={port};urp;StarOffice.ComponentContext"
    
    print(f"Connecting to LibreOffice at {host}:{port}...")
    for i in range(retries):
        try:
            ctx = resolver.resolve(connection_str)
            print("Connected to LibreOffice!")
            return ctx
        except Exception:
            time.sleep(sleep_time)
    
    return None

def convert_document(input_path, output_pdf_path):
    """
    Open the document, refresh all indexes (TOC), save it (DOCX),
    and export to PDF.
    """
    # Ensure paths are absolute or valid URLs
    if not os.path.exists(input_path):
        print(f"Error: Input file not found: {input_path}")
        sys.exit(1)

    ctx = wait_for_socket("localhost", 2002)
    if not ctx:
        print("Error: Could not connect to LibreOffice.")
        sys.exit(1)

    smgr = ctx.ServiceManager
    desktop = smgr.createInstanceWithContext("com.sun.star.frame.Desktop", ctx)

    input_url = f"file://{input_path}"
    print(f"Opening document: {input_url}")
    
    # Open hidden
    load_props = (
        PropertyValue(Name="Hidden", Value=True),
    )
    
    try:
        doc = desktop.loadComponentFromURL(input_url, "_blank", 0, load_props)
    except Exception as e:
        print(f"Error loading document: {e}")
        sys.exit(1)
        
    if not doc:
        print("Error: Document loaded as None.")
        sys.exit(1)

    try:
        print("Refreshing indexes (UpdateAllIndexes)...")
        doc.refresh()
        
        # Save the updated DOCX (overwrite the input inside the container)
        print("Saving updated DOCX...")
        doc.store()
        
        # Export to PDF
        print(f"Exporting to PDF: {output_pdf_path}")
        pdf_url = f"file://{output_pdf_path}"
        export_props = (
            PropertyValue(Name="FilterName", Value="writer_pdf_Export"),
        )
        doc.storeToURL(pdf_url, export_props)
        
        print("Conversion completed successfully.")
        
    except Exception as e:
        print(f"Error during processing: {e}")
        sys.exit(1)
    finally:
        doc.close(True)

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 lo_convert.py <input_docx> <output_pdf>")
        sys.exit(1)
        
    input_docx = sys.argv[1]
    output_pdf = sys.argv[2]
    
    convert_document(input_docx, output_pdf)
