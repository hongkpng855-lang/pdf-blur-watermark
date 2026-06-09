"""Generate a clean fillable Instrument of Transfer form PDF (multi-page)."""
import fitz

def generate_instrument_of_transfer(output_path):
    pw, ph = 595, 842
    ml = 72
    mr = 72
    cw = pw - ml - mr
    doc = fitz.open()
    field_id = [0]

    def new_page():
        p = doc.new_page(width=pw, height=ph)
        return p, 56  # starting y

    def text(page, x, y, txt, size=11, bold=False, color=(0,0,0)):
        fn = "Times-Bold" if bold else "Helvetica"
        page.insert_text((x, y), txt, fontsize=size, fontname=fn, color=color)

    def line(page, y, x1=None, x2=None):
        x1 = x1 or ml
        x2 = x2 or pw - mr
        page.draw_line((x1, y), (x2, y), color=(0,0,0), width=0.5)

    def flabel(page, x, y, label):
        page.insert_text((x, y), label, fontsize=9, fontname="Helvetica-Oblique", color=(0.4,0.4,0.4))

    def fld(page, y_pos, label_text, field_w=200, field_h=18, x_pos=None, value=""):
        x = x_pos or ml
        flabel(page, x, y_pos - 3, label_text)
        fy = y_pos + 2
        widget = fitz.Widget()
        widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        widget.field_name = label_text.replace(" ", "_")
        widget.rect = fitz.Rect(x, fy, x + field_w, fy + field_h)
        widget.text_font = "Helvetica"
        widget.text_font_size = 11
        widget.border_color = (0.42, 0.36, 0.91)
        widget.fill_color = (0.98, 0.97, 1.0)
        widget.text_color = (0, 0, 0)
        widget.border_width = 0.8
        if value:
            widget.field_value = value
            widget.text_value = value
        page.add_widget(widget)
        field_id[0] += 1
        return y_pos + field_h + 6

    def check_page(cur_page, y, needed=40):
        nonlocal page
        if y + needed > ph - 56:
            p, ny = new_page()
            page = p
            return page, ny
        return cur_page, y

    page, y = new_page()

    # ── Title ──
    y += 10
    text(page, ml, y, "INSTRUMENT OF TRANSFER", size=18, bold=True)
    y += 30
    line(page, y)
    y += 10
    text(page, ml, y, "POWERTRONIC HOLDINGS LIMITED", size=14, bold=True, color=(0,0,0.5))
    y += 6
    line(page, y)
    y += 24

    # ── Transferor ──
    text(page, ml, y, "I (We)", size=11)
    tx = ml + fitz.get_text_length("I (We) ", fontname="Helvetica", fontsize=11)
    page, y = check_page(page, y)
    y = fld(page, y, "Transferor Name", field_w=280, x_pos=tx)
    text(page, ml, y, "of", size=11)
    page, y = check_page(page, y, 50)
    y = fld(page, y, "Transferor Address", field_w=420, field_h=45, x_pos=ml + 20)
    y += 6

    # ── Consideration ──
    page, y = check_page(page, y)
    text(page, ml, y, "in consideration of the Sum of", size=11)
    y = fld(page, y, "Consideration Amount", field_w=320, x_pos=ml + 20)
    y += 4

    # ── Transferee ──
    page, y = check_page(page, y)
    text(page, ml, y, "paid to me (us) by", size=11)
    tx = ml + fitz.get_text_length("paid to me (us) by ", fontname="Helvetica", fontsize=11)
    y = fld(page, y, "Transferee Name", field_w=280, x_pos=tx)
    y += 2
    page, y = check_page(page, y)
    text(page, ml, y, "(occupation)", size=11, color=(0.3,0.3,0.3))
    y = fld(page, y, "Occupation", field_w=220, x_pos=ml + 80)
    page, y = check_page(page, y, 45)
    y = fld(page, y, "Transferee Address", field_w=420, field_h=40, x_pos=ml + 20)
    y += 6

    # ── Clause ──
    page, y = check_page(page, y)
    text(page, ml, y, '(hereinafter called "the said Transferee") do hereby transfer to the said Transferee the', size=11)
    y += 20

    # Share Number
    page, y = check_page(page, y)
    y = fld(page, y, "Share Number", field_w=100, x_pos=ml)
    y += 6

    # Continuing clause
    page, y = check_page(page, y, 70)
    clause = ('Standing in my (our) name in the Register of POWERTRONIC HOLDINGS LIMITED '
              'to hold unto the said Transferee his Executors, Administrators or Assigns, '
              'subject to the several conditions upon which I (We) hold the same at the time '
              'of execution hereof. And I (we) the said Transferee do hereby agree to take '
              'the said Shares subject to the same conditions.')
    words = clause.split()
    lt = ""
    for w in words:
        test = lt + " " + w if lt else w
        if fitz.get_text_length(test, fontname="Helvetica", fontsize=10) < cw:
            lt = test
        else:
            text(page, ml, y, lt, size=10)
            y += 14
            lt = w
    if lt:
        text(page, ml, y, lt, size=10)
        y += 14
    y += 10

    # ── Date ──
    page, y = check_page(page, y)
    text(page, ml, y, "Witness our hands the", size=11)
    tx = ml + fitz.get_text_length("Witness our hands the ", fontname="Helvetica", fontsize=11)
    y = fld(page, y, "Day", field_w=50, x_pos=tx)
    text(page, ml + tx + 55, y - 16, "day of", size=11)
    y = fld(page, y, "Month", field_w=120, x_pos=ml + tx + 100)
    y = fld(page, y, "Year", field_w=80, x_pos=ml + tx + 230)
    y += 15

    # ── Transferor Witness ──
    page, y = check_page(page, y, 120)
    text(page, ml, y, "Witness to the signature(s) of", size=11, bold=True)
    y += 18
    y = fld(page, y, "Witness Name", field_w=220)
    page, y = check_page(page, y, 70)
    y = fld(page, y, "Witness Address", field_w=420, field_h=65)
    y += 5
    line(page, y, ml, ml + 220)
    y += 10
    text(page, ml, y, "(Transferor)", size=10, color=(0.3,0.3,0.3))
    y = fld(page, y, "Transferor Signature Name", field_w=280)
    y += 20

    # ── Transferee Witness ──
    page, y = check_page(page, y, 180)
    text(page, ml, y, "Witness to the signature(s) of", size=11, bold=True)
    y += 18
    y = fld(page, y, "Witness Name 2", field_w=220)
    page, y = check_page(page, y, 70)
    y = fld(page, y, "Witness Address 2", field_w=420, field_h=65)
    y += 5
    page, y = check_page(page, y, 60)
    text(page, ml, y, "For and on behalf of", size=11, bold=True)
    y += 18
    y = fld(page, y, "Company", field_w=320, value="IDEAL TRADE INVESTMENT LIMITED")
    y += 5
    line(page, y, ml, ml + 220)
    y += 10
    text(page, ml, y, "Authorized Signature(s)", size=10, color=(0.3,0.3,0.3))
    y += 22
    line(page, y, ml, ml + 220)
    y += 10
    text(page, ml, y, "(Transferee)", size=10, color=(0.3,0.3,0.3))
    y = fld(page, y, "Transferee Signature Name", field_w=320)

    doc.save(output_path, garbage=4, deflate=True)
    doc.close()
    return output_path

if __name__ == "__main__":
    generate_instrument_of_transfer("/tmp/instrument_of_transfer_fillable.pdf")
    import os
    print(f"Size: {os.path.getsize('/tmp/instrument_of_transfer_fillable.pdf')} bytes")
    doc = fitz.open("/tmp/instrument_of_transfer_fillable.pdf")
    print(f"Pages: {len(doc)}")
    for pi in range(len(doc)):
        page = doc[pi]
        widgets = list(page.widgets())
        print(f"  Page {pi+1}: {len(widgets)} fields")
        for w in widgets:
            print(f"    {w.field_name}: {w.rect}")
    doc.close()
