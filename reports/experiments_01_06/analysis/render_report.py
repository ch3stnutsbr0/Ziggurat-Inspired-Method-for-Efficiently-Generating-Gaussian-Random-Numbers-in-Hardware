"""Render the report Markdown to a typeset PDF, with repeated table headers."""
import argparse,html,re
from pathlib import Path
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle,Image,PageBreak,KeepTogether

ROOT=Path(__file__).resolve().parents[1]
DEFAULT_FONTS=Path('/Users/liubenli/anaconda3/lib/python3.12/site-packages/matplotlib/mpl-data/fonts/ttf')
def main(font_dir=DEFAULT_FONTS):
    for name,file in [('Body','DejaVuSerif.ttf'),('BodyBold','DejaVuSerif-Bold.ttf'),('Sans','DejaVuSans.ttf'),('SansBold','DejaVuSans-Bold.ttf')]:
        pdfmetrics.registerFont(TTFont(name,str(font_dir/file)))
    pdfmetrics.registerFontFamily('Body',normal='Body',bold='BodyBold',italic='Body',boldItalic='BodyBold')
    pdfmetrics.registerFontFamily('Sans',normal='Sans',bold='SansBold',italic='Sans',boldItalic='SansBold')
    navy=colors.HexColor('#203e53');gray=colors.HexColor('#53636c')
    styles={
        'body':ParagraphStyle('body',fontName='Body',fontSize=9.4,leading=14.4,spaceAfter=8,textColor=colors.HexColor('#24323a'),splitLongWords=True),
        'h1':ParagraphStyle('h1',fontName='SansBold',fontSize=23,leading=30,textColor=navy,spaceAfter=26),
        'h2':ParagraphStyle('h2',fontName='SansBold',fontSize=15,leading=20,textColor=navy,spaceBefore=17,spaceAfter=10,keepWithNext=True),
        'h3':ParagraphStyle('h3',fontName='SansBold',fontSize=11,leading=15,textColor=navy,spaceBefore=12,spaceAfter=7,keepWithNext=True),
        'cell':ParagraphStyle('cell',fontName='Sans',fontSize=7.1,leading=10,textColor=colors.HexColor('#24323a'),splitLongWords=True),
        'head':ParagraphStyle('head',fontName='SansBold',fontSize=7.2,leading=10,textColor=colors.white),
        'caption':ParagraphStyle('caption',fontName='Sans',fontSize=8.1,leading=11.7,textColor=gray,spaceAfter=12),
        'tablecaption':ParagraphStyle('tablecaption',fontName='Sans',fontSize=8.1,leading=11.7,textColor=gray,spaceAfter=8,keepWithNext=True),
    }
    width=A4[0]-100
    def inline(s):
        s=s.replace('–','-').replace('—','-').replace('‑','-')
        s=html.escape(s)
        s=re.sub(r'\*\*(.+?)\*\*',r'<b>\1</b>',s)
        s=re.sub(r'`(.+?)`',r'<font name="Sans">\1</font>',s)
        s=re.sub(r'\[([^\]]+)\]\((https?://[^)]+)\)',r'<link href="\2" color="#255f85">\1</link>',s)
        return s
    lines=(ROOT/'report.md').read_text().splitlines();story=[];i=0;table_count=0
    while i<len(lines):
        line=lines[i].strip()
        if not line:i+=1;continue
        if line.startswith('# '):
            story.append(Spacer(1,60));story.append(Paragraph(inline(line[2:]),styles['h1']));i+=1;continue
        if line.startswith('## '):
            title=line[3:]
            if title.startswith(('1. Introduction','Appendix A.','Appendix C.','References')):story.append(PageBreak())
            story.append(Paragraph(inline(title),styles['h2']));i+=1;continue
        if line.startswith('### '):story.append(Paragraph(inline(line[4:]),styles['h3']));i+=1;continue
        if line.startswith('!['):
            p=ROOT/re.search(r'\]\(([^)]+)\)',line).group(1)
            from PIL import Image as PILImage
            with PILImage.open(p) as im:w,h=im.size
            scale=min(width/w,425/h)
            block=[Image(str(p),width=w*scale,height=h*scale),Spacer(1,8)];i+=1
            while i<len(lines) and not lines[i].strip():i+=1
            if i<len(lines) and lines[i].startswith('Figure '):
                block.append(Paragraph(inline(lines[i]),styles['caption']));i+=1
            story.append(KeepTogether(block));continue
        if line.startswith('|'):
            rows=[]
            while i<len(lines) and lines[i].strip().startswith('|'):
                cells=[x.strip() for x in lines[i].strip().strip('|').split('|')]
                if not all(re.fullmatch(r'[:\- ]+',c) for c in cells):rows.append(cells)
                i+=1
            n=len(rows[0]);weights=[1]*n
            if n==5 and 'Objective' in rows[0]:weights=[1.05,1.1,1.45,1.05,1.75]
            elif n==5 and 'Chi-square: stat; p; result' in rows[0]:weights=[1.05,1.25,1.25,1.25,1.25]
            elif n==6 and rows[0][0]=='Use case':weights=[1.05,1.25,1.65,.7,1.7,1.15]
            elif n==3:weights=[1,2.5,2.5]
            widths=[width*w/sum(weights) for w in weights]
            data=[[Paragraph(inline(c),styles['head' if j==0 else 'cell']) for c in row] for j,row in enumerate(rows)]
            t=Table(data,colWidths=widths,repeatRows=1,hAlign='LEFT')
            t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),navy),('VALIGN',(0,0),(-1,-1),'TOP'),
                ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#f0f4f5')]),
                ('BOTTOMPADDING',(0,0),(-1,-1),6),('TOPPADDING',(0,0),(-1,-1),6),
                ('LEFTPADDING',(0,0),(-1,-1),5),('RIGHTPADDING',(0,0),(-1,-1),5),
                ('LINEBELOW',(0,0),(-1,0),.5,navy),('LINEBELOW',(0,-1),(-1,-1),.4,colors.HexColor('#b8c7cf'))]))
            story.extend([t,Spacer(1,12)]);table_count+=1;continue
        para=[line];i+=1
        while i<len(lines) and lines[i].strip() and not lines[i].startswith(('#','|','![')):
            para.append(lines[i].strip());i+=1
        s=' '.join(para);caption=s.startswith(('Figure ','**Table '))
        story.append(Paragraph(inline(s),styles['tablecaption' if s.startswith('**Table ') else 'caption' if caption else 'body']))
    def page(canvas,doc):
        canvas.saveState();canvas.setStrokeColor(colors.HexColor('#b6c6ce'));canvas.setLineWidth(.4)
        canvas.line(50,A4[1]-36,A4[0]-50,A4[1]-36)
        canvas.setFont('Sans',7.3);canvas.setFillColor(gray)
        canvas.drawString(50,A4[1]-28,'GAUSSIAN RANDOM NUMBER GENERATION  /  EXPERIMENTS 01-06')
        canvas.drawString(50,27,'Existing-results research report | 15 October 2026')
        canvas.drawRightString(A4[0]-50,27,str(doc.page));canvas.restoreState()
    doc=SimpleDocTemplate(str(ROOT/'report.pdf'),pagesize=A4,leftMargin=50,rightMargin=50,topMargin=52,bottomMargin=49,
        title='Accuracy-Performance Trade-offs in Classical and Trapezoidal Ziggurat Gaussian Random Number Generators',author='Project research report',allowSplitting=True)
    doc.build(story,onFirstPage=page,onLaterPages=page)
    print('Rendered report.pdf;',table_count,'tables')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--font-dir',type=Path,default=DEFAULT_FONTS);a=p.parse_args();main(a.font_dir)
