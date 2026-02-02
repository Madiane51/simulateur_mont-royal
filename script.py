import streamlit as st
import pandas as pd
import numpy as np
import os
from io import BytesIO
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from datetime import datetime
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, JsCode
import base64
import math

# Configuration de la page
st.set_page_config(
    page_title="Simulateur Mont-Royal", 
    layout="wide",
    page_icon="🕶️",
    initial_sidebar_state="expanded"
)

# Styles CSS personnalisés
st.markdown("""
<style>
    .main-header {
        background: linear-gradient(90deg, #f68b1f 0%, #ff6b35 100%);
        color: white;
        padding: 1rem;
        border-radius: 10px;
        margin-bottom: 2rem;
        text-align: center;
    }
    .metric-card {
        background: #f8f9fa;
        padding: 1rem;
        border-radius: 10px;
        border-left: 4px solid #f68b1f;
        margin: 0.5rem 0;
    }
    .success-message {
        background: #d4edda;
        color: #155724;
        padding: 1rem;
        border-radius: 5px;
        border: 1px solid #c3e6cb;
        margin: 1rem 0;
    }
    .warning-message {
        background: #fff3cd;
        color: #856404;
        padding: 1rem;
        border-radius: 5px;
        border: 1px solid #ffeaa7;
        margin: 1rem 0;
    }
    .sidebar .sidebar-content {
        background: linear-gradient(180deg, #f8f9fa 0%, #e9ecef 100%);
    }
    .editable-cell {
        background-color: #fffacd !important;
        border: 2px solid #f68b1f !important;
    }
</style>
""", unsafe_allow_html=True)

# Fonction pour générer un numéro de proposition automatique
def generate_proposal_number():
    today = datetime.now().strftime("%Y%m%d")
    hour_minute = datetime.now().strftime("%H%M")
    return f"PROP-{today}-{hour_minute}"

# Fonction utilitaire pour l'arrondi supérieur au centime
def round_up_price(x):
    if pd.isna(x) or x == 0:
        return 0.0
    # On arrondit d'abord à 4 décimales pour éviter les erreurs de flottants (ex: 10.00000001)
    # Puis on applique le plafond au centime
    return np.ceil(round(x, 4) * 100) / 100

# Fonction pour encoder une image en base64
def get_base64_image(image_path):
    if os.path.exists(image_path):
        with open(image_path, "rb") as img_file:
            return base64.b64encode(img_file.read()).decode()
    return None

# Fonction pour calculer les valeurs dérivées
def calculate_derived_values(df):
    """Calcule les valeurs dérivées - NOUVELLE LOGIQUE"""
    df = df.copy()
    
    # LOGIQUE MODIFIÉE : La remise est calculée à partir du Prix Brut HT
    # Si Remise (%) est renseignée, calculer Remise (€) à partir du Prix Brut HT
    for idx in df.index:
        if pd.notna(df.loc[idx, 'Remise (%)']) and df.loc[idx, 'Remise (%)'] != 0:
            val_remise = df.loc[idx, 'Prix Brut HT'] * df.loc[idx, 'Remise (%)'] / 100
            df.loc[idx, 'Remise (€)'] = val_remise # L'arrondi se fera à la fin
    
    # Calcul Prix net après remise (colonne I)
    df['Prix net après remise'] = df.apply(lambda row: 
        row['Prix Net HT'] - row['Remise (€)'] - (row['Remise autre (€)'] if pd.notna(row['Remise autre (€)']) else 0),
        axis=1)
    
    # Calcul PPGC HT (colonne K)
    df['PPGC HT'] = df.apply(lambda row:
        row['Prix net après remise'] * row['Coeff'] if pd.notna(row['Coeff']) and row['Coeff'] != 0
        else 0, axis=1)
    
    # Calcul PPGC TTC (on ajoute la TVA de 20%)
    df['PPGC TTC'] = df['PPGC HT'] * 1.20
    
    # Calcul Prix Net Net (colonne Q)
    df['Prix Net Net'] = df.apply(lambda row:
        row['Prix net après remise'] - (row['Prix net après remise'] * row['RFA'] / 100) if pd.notna(row['RFA']) and row['RFA'] != 0
        else row['Prix net après remise'], axis=1)
    
    # Calcul des marges
    df['Marge brute (€)'] = df['PPGC HT'] - df['Prix Brut HT']
    df['Marge nette (€)'] = df['PPGC HT'] - df['Prix net après remise']
    
    # Calcul Taux de marque
    df['Taux de marque'] = df.apply(lambda row:
        (row['Marge nette (€)'] / row['PPGC HT']) * 100 if row['PPGC HT'] != 0 else 0, axis=1)
    
    # --- APPLICATION DE L'ARRONDI SUPERIEUR (Ceiling) ---
    monetary_cols = ['Prix Brut HT', 'Prix Net HT', 'Remise (€)', 'Remise autre (€)', 
                     'Prix net après remise', 'PPGC HT', 'PPGC TTC', 
                     'Marge brute (€)', 'Marge nette (€)', 'Prix Net Net']
    
    for col in monetary_cols:
        if col in df.columns:
            df[col] = df[col].apply(round_up_price)
            
    return df

# Fonction pour générer le PDF amélioré
def generate_pdf(df, proposal_number, buffer, client_info=None, remise_modes=None):
    # On travaille sur une copie pour ne pas modifier l'affichage écran
    df = df.copy()
    
    if 'Catégorie produit' in df.columns:
        def classer_categorie(valeur):
            # Convertir en chaine de caractères propre (sans espaces inutiles)
            val_str = str(valeur).strip() if pd.notna(valeur) else ""
            
            # Si c'est exactement UO ou Progressif, on garde
            if val_str in ['UO', 'Progressif']:
                return val_str
            # Sinon (vide, null, ou tout autre nom), on met dans Divers
            else:
                return "Divers"

        df['Catégorie produit'] = df['Catégorie produit'].apply(classer_categorie)

    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=2*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    story = []
    
    # Logo (si disponible)
    logo_path = "mont-royal-logo.jpg"
    if os.path.exists(logo_path):
        try:
            img = Image(logo_path, width=5*cm, height=3*cm)
            img.hAlign = 'CENTER'
            story.append(img)
            story.append(Spacer(1, 12))
        except:
            pass
    
    # En-tête avec style amélioré
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Title'],
        fontSize=24,
        alignment=1,
        textColor=colors.HexColor("#f68b1f"),
        spaceAfter=20,
        fontName='Helvetica-Bold'
    )
    
    story.append(Paragraph("Proposition Commerciale", title_style))
    story.append(Paragraph("Mont-Royal - Manufacture française d'optique", styles['Heading3']))
    story.append(Spacer(1, 20))
    
    # Informations de la proposition
    info_style = ParagraphStyle(
        'InfoStyle',
        parent=styles['Normal'],
        fontSize=12,
        leftIndent=0,
        rightIndent=0,
        spaceAfter=6
    )
    
    story.append(Paragraph(f"<b>N° de proposition :</b> {proposal_number}", info_style))
    story.append(Paragraph(f"<b>Date :</b> {datetime.now().strftime('%d/%m/%Y à %H:%M')}", info_style))
    
    if client_info:
        story.append(Paragraph(f"<b>Client :</b> {client_info}", info_style))
    
    story.append(Spacer(1, 20))
    
    # Traitement par catégorie
    # On trie pour avoir un ordre cohérent (Divers sera souvent à la fin ou au début selon l'ordre alphabétique)
    # Pour forcer l'ordre UO -> Progressif -> Divers, on peut faire un tri personnalisé, mais le tri alphabétique suffit souvent
    categories = sorted(df['Catégorie produit'].unique())
    
    for category in categories:
        cat_df = df[df['Catégorie produit'] == category]
        if not cat_df.empty:
            # Titre de catégorie
            category_style = ParagraphStyle(
                'CategoryStyle',
                parent=styles['Heading2'],
                fontSize=16,
                textColor=colors.HexColor("#2c3e50"),
                spaceAfter=12,
                borderWidth=1,
                borderColor=colors.HexColor("#f68b1f"),
                borderPadding=8,
                backColor=colors.HexColor("#fff5f0")
            )
            
            story.append(Paragraph(f"Catégorie : {category}", category_style))
            story.append(Spacer(1, 10))
            
            # En-tête du tableau
            table_header = ['Libellé article', 'Version']
            
            # Déterminer si on doit afficher les colonnes de remise
            show_remise_pct = False
            show_remise_euros = False
            
            if remise_modes:
                for idx in cat_df.index:
                    mode = remise_modes.get(idx, "En %")
                    if mode == "En %":
                        show_remise_pct = True
                    else:
                        show_remise_euros = True
            else:
                show_remise_pct = True
                show_remise_euros = True
            
            if show_remise_pct:
                table_header.append('Remise (%)')
            if show_remise_euros:
                table_header.append('Remise (€)')
            
            table_header.extend(['Prix Net HT', 'Prix après remise', 'PPGC TTC', 'Marge nette', 'RFA', 'Prix Net Net'])
            
            table_data = [table_header]
            
            # Largeurs de colonnes
            col_widths = [3*cm, 1.8*cm]
            if show_remise_pct:
                col_widths.append(1.5*cm)
            if show_remise_euros:
                col_widths.append(1.5*cm)
            col_widths.extend([2*cm, 2.5*cm, 2*cm, 2*cm, 1.5*cm, 2*cm])
            
            for idx, row in cat_df.iterrows():
                # Gestion du wrapping pour les libellés longs
                libelle_text = str(row['Libellé article']) if pd.notna(row['Libellé article']) else ""
                libelle_para = Paragraph(libelle_text, styles['Normal'])
                
                version_text = str(row['Version']) if pd.notna(row['Version']) else ""
                
                row_data = [libelle_para, version_text]
                
                mode = remise_modes.get(idx, "En %") if remise_modes else "En %"
                
                if show_remise_pct:
                    if mode == "En %":
                        remise_pct = row['Remise (%)']
                        row_data.append(f"{remise_pct:.1f}%" if remise_pct > 0 else "-")
                    else:
                        row_data.append("-")
                
                if show_remise_euros:
                    if mode == "En €":
                        row_data.append(f"{row['Remise (€)']:.2f}€" if row['Remise (€)'] > 0 else "-")
                    else:
                        row_data.append("-")
                
                row_data.extend([
                    f"{row['Prix Net HT']:.2f}€",
                    f"{row['Prix net après remise']:.2f}€",
                    f"{row['PPGC TTC']:.2f}€",
                    f"{row['Marge nette (€)']:.2f}€",
                    f"{row['RFA']:.0f}%" if pd.notna(row['RFA']) and row['RFA'] != 0 else "-",
                    f"{row['Prix Net Net']:.2f}€"
                ])
                
                table_data.append(row_data)
            
            # Création du tableau
            table = Table(table_data, colWidths=col_widths)
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#f68b1f")),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 8),
                ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
                ('VALIGN', (0, 0), (-1, 0), 'MIDDLE'),
                ('BACKGROUND', (0, 1), (-1, -1), colors.white),
                ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
                ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 1), (-1, -1), 7),
                ('ALIGN', (0, 1), (-1, -1), 'CENTER'),
                ('VALIGN', (0, 1), (-1, -1), 'MIDDLE'),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('LINEBELOW', (0, 0), (-1, 0), 2, colors.HexColor("#f68b1f")),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8f9fa")]),
            ]))
            
            story.append(table)
            story.append(Spacer(1, 15))
    
    # Pied de page
    story.append(Spacer(1, 30))
    footer_style = ParagraphStyle(
        'FooterStyle',
        parent=styles['Normal'],
        fontSize=10,
        alignment=1,
        textColor=colors.grey,
        spaceAfter=6
    )
    
    story.append(Paragraph("Mont-Royal - Manufacture française d'optique", footer_style))
    story.append(Paragraph("Cette proposition est valable 30 jours à compter de la date d'émission", footer_style))
    
    doc.build(story)

# Fonction pour charger les données par défaut
def load_default_data():
    """Charge automatiquement un fichier Excel s'il existe"""
    default_files = ['articles.xlsx', 'data.xlsx', 'mont_royal.xlsx', 'base_donnees.xlsx']
    for filename in default_files:
        if os.path.exists(filename):
            try:
                df = pd.read_excel(filename)
                return initialize_dataframe_columns(df)
            except Exception as e:
                st.error(f"Erreur lors du chargement de {filename}: {str(e)}")
                continue
    return pd.DataFrame()

# Fonction pour initialiser les colonnes manquantes
def initialize_dataframe_columns(df):
    """Initialise les colonnes manquantes avec des valeurs par défaut"""
    required_columns = {
        'Catégorie produit': '',
        'Libellé article': '',
        'Version': '',
        'Code EDI': '',
        'Prix Brut HT': 0.0,
        'Prix Net HT': 0.0,
        'Remise (€)': 0.0,
        'Remise (%)': 0.0,
        'Remise autre (€)': 0.0,
        'Prix net après remise': 0.0,
        'Coeff': 1.0,
        'PPGC HT': 0.0,
        'PPGC TTC': 0.0,
        'Marge brute (€)': 0.0,
        'Marge nette (€)': 0.0,
        'Taux de marque': 0.0,
        'RFA': 0.0,
        'Prix Net Net': 0.0
    }
    
    for col, default_value in required_columns.items():
        if col not in df.columns:
            df[col] = default_value
    
    # Conversion des types
    numeric_columns = ['Prix Brut HT', 'Prix Net HT', 'Remise (€)', 'Remise (%)', 'Remise autre (€)', 
                      'Prix net après remise', 'Coeff', 'PPGC HT', 'PPGC TTC', 
                      'Marge brute (€)', 'Marge nette (€)', 'Taux de marque', 'RFA', 'Prix Net Net']
    
    for col in numeric_columns:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
            
    # --- APPLICATION DE L'ARRONDI SUPERIEUR IMMEDIATEMENT AU CHARGEMENT ---
    cols_to_round = ['Prix Brut HT', 'Prix Net HT']
    for col in cols_to_round:
        if col in df.columns:
             df[col] = df[col].apply(round_up_price)
    
    return df

# Fonction pour valider les colonnes
def validate_dataframe(df):
    """Valide que le DataFrame contient les colonnes essentielles"""
    essential_columns = [
        'Catégorie produit', 'Libellé article', 'Version', 'Code EDI', 'Prix Brut HT', 'Prix Net HT'
    ]
    
    missing_columns = [col for col in essential_columns if col not in df.columns]
    if missing_columns:
        st.error(f"⚠️ Colonnes essentielles manquantes: {', '.join(missing_columns)}")
        return False
    return True

# Interface principale
def main():
    # En-tête principal
    st.markdown("""
    <div class="main-header">
        <h1>Simulateur Mont-Royal</h1>
        <p>Manufacture française d'optique - Outil de génération de propositions commerciales</p>
    </div>
    """, unsafe_allow_html=True)
    
    # Initialisation des variables de session
    if 'articles_data' not in st.session_state:
        st.session_state['articles_data'] = load_default_data()
    if 'selected_articles' not in st.session_state:
        st.session_state['selected_articles'] = pd.DataFrame()
    if 'remise_modes' not in st.session_state:
        st.session_state['remise_modes'] = {}
    
    # Sidebar - Chargement de fichier
    with st.sidebar:
        st.header("📂 Gestion des données")
        
        uploaded_file = st.file_uploader(
            "Charger un fichier Excel", 
            type=["xlsx", "xls"],
            help="Chargez votre base de données d'articles au format Excel"
        )
        
        if uploaded_file:
            try:
                df_uploaded = pd.read_excel(uploaded_file)
                if validate_dataframe(df_uploaded):
                    df_uploaded = initialize_dataframe_columns(df_uploaded)
                    st.session_state['articles_data'] = df_uploaded
                    st.success(f"✅ Fichier chargé: {len(df_uploaded)} articles")
                else:
                    st.error("❌ Format de fichier incorrect")
            except Exception as e:
                st.error(f"❌ Erreur lors du chargement: {str(e)}")
        
        # Informations sur les données
        if not st.session_state['articles_data'].empty:
            st.info(f"📊 **{len(st.session_state['articles_data'])}** articles en base")
            
            # Répartition par catégorie
            if 'Catégorie produit' in st.session_state['articles_data'].columns:
                categories = st.session_state['articles_data']['Catégorie produit'].value_counts()
                st.write("**Répartition par catégorie:**")
                for cat, count in categories.items():
                    st.write(f"• {cat}: {count} articles")
        
        # Actions sur la sélection
        st.header("🛍️ Actions")
        if not st.session_state['selected_articles'].empty:
            if st.button("🗑️ Vider le panier", type="secondary"):
                st.session_state['selected_articles'] = pd.DataFrame()
                st.session_state['remise_modes'] = {}
                st.rerun()
    
    # Contenu principal
    if st.session_state['articles_data'].empty:
        st.warning("⚠️ Aucune donnée chargée. Veuillez charger un fichier Excel dans la barre latérale.")
        st.info("💡 L'application recherche automatiquement les fichiers: articles.xlsx, data.xlsx, mont_royal.xlsx, base_donnees.xlsx")
        return
    
    # Filtres de recherche
    with st.expander("🔍 Filtres de recherche", expanded=True):
        col1, col2, col3 = st.columns(3)
        
        with col1:
            libelle_filter = st.text_input(
                "🏷️ Libellé article:",
                placeholder="Saisissez le nom de l'article...",
                help="Recherche partielle dans le libellé"
            )
        
        with col2:
            # Extraction dynamique des versions disponibles
            versions_available = sorted(st.session_state['articles_data']['Version'].dropna().unique())
            version_filter = st.selectbox(
                "🔖 Version:",
                [""] + list(versions_available),
                help="Sélectionnez une version spécifique"
            )
        
        with col3:
            edi_filter = st.text_input(
                "🏷️ Code EDI:",
                placeholder="Code EDI...",
                help="Recherche exacte ou partielle"
            )
        
        # Application des filtres
        df_filtered = st.session_state['articles_data'].copy()
        
        if libelle_filter:
            df_filtered = df_filtered[
                df_filtered['Libellé article'].str.contains(libelle_filter, case=False, na=False)
            ]
        
        if version_filter:
            df_filtered = df_filtered[
                df_filtered['Version'].astype(str).str.contains(version_filter, case=False, na=False)
            ]
        
        if edi_filter:
            df_filtered = df_filtered[
                df_filtered['Code EDI'].astype(str).str.contains(edi_filter, case=False, na=False)
            ]
        
        # Affichage du nombre de résultats
        st.info(f"📋 {len(df_filtered)} article(s) trouvé(s)")
    
    # Affichage des articles disponibles
    if not df_filtered.empty:
        st.subheader("📄 Articles disponibles")
        st.caption("Sélectionnez les articles à ajouter à votre proposition")
        
        # Configuration de la grille
        gb = GridOptionsBuilder.from_dataframe(df_filtered)
        gb.configure_column("Taux de marque", hide=True)
        gb.configure_selection("multiple", use_checkbox=True, groupSelectsChildren=True)
        gb.configure_grid_options(domLayout='normal')
        gb.configure_default_column(enablePivot=True, enableValue=True, enableRowGroup=True)
        
        # Mise en forme des colonnes
        gb.configure_column("Prix Brut HT", type=["numericColumn", "numberColumnFilter", "customNumericFormat"], valueFormatter="data.value.toFixed(2) + '€'")
        gb.configure_column("Prix Net HT", type=["numericColumn", "numberColumnFilter", "customNumericFormat"], valueFormatter="data.value.toFixed(2) + '€'")
        gb.configure_column("PPGC TTC", type=["numericColumn", "numberColumnFilter", "customNumericFormat"], valueFormatter="data.value.toFixed(2) + '€'")
        gb.configure_column("Marge nette (€)", type=["numericColumn", "numberColumnFilter", "customNumericFormat"], valueFormatter="data.value.toFixed(2) + '€'")
        gb.configure_column("Prix Net Net", type=["numericColumn", "numberColumnFilter", "customNumericFormat"], valueFormatter="data.value.toFixed(2) + '€'")
        
        grid_response = AgGrid(
            df_filtered,
            gridOptions=gb.build(),
            update_mode=GridUpdateMode.SELECTION_CHANGED,
            theme="streamlit",
            height=400,
            allow_unsafe_jscode=True
        )
        
        selected_rows = grid_response['selected_rows']
        
        # Bouton d'ajout au panier
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            if st.button("🛒 Ajouter au panier", type="primary", use_container_width=True):
                if isinstance(selected_rows, pd.DataFrame):
                    has_selection = not selected_rows.empty
                else:
                    has_selection = bool(selected_rows)
                
                if has_selection:
                    selected_df = pd.DataFrame(selected_rows)
                    
                    if st.session_state['selected_articles'].empty:
                        st.session_state['selected_articles'] = selected_df
                    else:
                        # Éviter les doublons basés sur le Code EDI
                        existing_edis = st.session_state['selected_articles']['Code EDI'].tolist()
                        new_articles = selected_df[~selected_df['Code EDI'].isin(existing_edis)]
                        
                        if not new_articles.empty:
                            st.session_state['selected_articles'] = pd.concat([
                                st.session_state['selected_articles'], 
                                new_articles
                            ], ignore_index=True)
                        
                        duplicates = len(selected_df) - len(new_articles)
                        if duplicates > 0:
                            st.warning(f"⚠️ {duplicates} article(s) déjà dans le panier (ignoré(s))")
                    
                    st.success(f"✅ {len(selected_df)} article(s) ajouté(s) au panier")
                    st.rerun()
                else:
                    st.warning("⚠️ Veuillez sélectionner au moins un article")
    
    # Affichage du panier avec modification possible
    if not st.session_state['selected_articles'].empty:
        st.markdown("---")
        st.subheader("🛍️ Panier de sélection avec ajustements commerciaux")
        st.info("💡 Choisissez le mode de saisie de la remise (en % ou en €) pour chaque article. "
                "Les valeurs sont mémorisées et les calculs se mettent à jour automatiquement.")
        
        # Parcours des articles du panier
        for idx, row in st.session_state['selected_articles'].iterrows():
            with st.expander(f"📝 {row['Libellé article']} - {row['Version']}", expanded=False):
                # Déterminer/initialiser le mode de saisie (par défaut : % si non nul, sinon €)
                mode_key = f"remise_mode_{idx}"
                if mode_key not in st.session_state:
                    st.session_state[mode_key] = "En %" if float(row.get('Remise (%)', 0) or 0) > 0 else "En €"
                
                # Sélecteur horizontal du mode
                mode = st.radio(
                    "Mode de saisie de la remise",
                    options=["En %", "En €"],
                    horizontal=True,
                    key=mode_key,
                    help="Choisissez comment saisir la remise pour cet article."
                )
                
                # Stocker le mode de remise pour cet article
                st.session_state['remise_modes'][idx] = mode
                
                # Mise en page des champs
                col1, col2, col3, col4, col5 = st.columns([1.2, 1.5, 1.5, 1.2, 1.6])
                
                with col1:
                    st.write(f"**Prix Brut HT :** {float(row['Prix Brut HT']):.2f}€")
                    st.write(f"**Prix Net HT :** {float(row['Prix Net HT']):.2f}€")
                
                # --- Saisie de la remise selon le mode ---
                with col2:
                    if mode == "En %":
                        # Champ Remise (%) actif
                        pct_key = f"remise_pct_{idx}"
                        current_pct = float(st.session_state['selected_articles'].at[idx, 'Remise (%)'])
                        new_pct = st.number_input(
                            "Remise (%)",
                            min_value=0.0, max_value=100.0, step=0.5,
                            value=current_pct,
                            key=pct_key,
                            help="Remise (en %) du Prix Brut HT"
                        )
                        # MÀJ du % en session_state
                        st.session_state['selected_articles'].at[idx, 'Remise (%)'] = new_pct
                        # Calcul de la remise en € à partir du % (priorité au % si non nul)
                        euros_from_pct = float(st.session_state['selected_articles'].at[idx, 'Prix Brut HT']) * new_pct / 100.0
                        # On stocke tel quel, l'arrondi se fera au calcul global
                        st.session_state['selected_articles'].at[idx, 'Remise (€)'] = euros_from_pct
                    else:  # mode == "En €"
                        # Champ Remise (€) actif
                        euros_key = f"remise_euros_{idx}"
                        current_euros = float(st.session_state['selected_articles'].at[idx, 'Remise (€)'])
                        new_euros = st.number_input(
                            "Remise (€)",
                            min_value=0.0, step=0.1,
                            value=current_euros,
                            key=euros_key,
                            help="Montant de la remise en euros"
                        )
                        # MÀJ du € en session_state
                        st.session_state['selected_articles'].at[idx, 'Remise (€)'] = new_euros
                        # Forcer le % à 0 pour éviter tout conflit lors des recalculs
                        st.session_state['selected_articles'].at[idx, 'Remise (%)'] = 0.0
                
                with col3:
                    # Affiche le champ complémentaire en lecture seule selon le mode
                    if mode == "En %":
                        # Remise (€) calculée automatiquement et affichée en RO
                        remise_calculee = float(st.session_state['selected_articles'].at[idx, 'Remise (€)'])
                        # On affiche l'arrondi pour la clarté
                        remise_aff = round_up_price(remise_calculee)
                        st.number_input(
                            "Remise (€) (calculée)",
                            min_value=0.0, step=0.1,
                            value=remise_aff,
                            key=f"remise_euros_ro_{idx}",
                            disabled=True,
                            help="Calculée automatiquement à partir de la remise en %"
                        )
                    else:
                        # Remise (%) désactivée et forcée à 0
                        st.number_input(
                            "Remise (%) (désactivée)",
                            min_value=0.0, max_value=100.0, step=0.5,
                            value=0.0,
                            key=f"remise_pct_ro_{idx}",
                            disabled=True,
                            help="Désactivée en mode 'En €' (forcée à 0)"
                        )
                
                with col4:
                    # Coefficient
                    coeff = st.number_input(
                        "Coefficient",
                        min_value=0.0,
                        value=float(row['Coeff']) if float(row['Coeff']) != 0 else 1.0,
                        step=0.1,
                        key=f"coeff_{idx}",
                        help="Coefficient multiplicateur pour le PPGC"
                    )
                    st.session_state['selected_articles'].at[idx, 'Coeff'] = coeff
                    
                    # RFA
                    rfa = st.number_input(
                        "RFA (%)",
                        min_value=0.0, max_value=100.0,
                        value=float(row['RFA']),
                        step=1.0,
                        key=f"rfa_{idx}",
                        help="Pourcentage RFA à appliquer"
                    )
                    st.session_state['selected_articles'].at[idx, 'RFA'] = rfa
                
                with col5:
                    # Recalcule d'aperçu en temps réel (en respectant la logique globale avec arrondi)
                    current_remise_euros = round_up_price(float(st.session_state['selected_articles'].at[idx, 'Remise (€)']))
                    current_remise_autre = round_up_price(float(st.session_state['selected_articles'].at[idx, 'Remise autre (€)'])) if 'Remise autre (€)' in st.session_state['selected_articles'].columns else 0.0
                    current_coeff = float(st.session_state['selected_articles'].at[idx, 'Coeff'])
                    current_rfa = float(st.session_state['selected_articles'].at[idx, 'RFA'])
                    
                    prix_net_ht = round_up_price(float(st.session_state['selected_articles'].at[idx, 'Prix Net HT']))
                    
                    prix_apres_remise = round_up_price(prix_net_ht - current_remise_euros - (current_remise_autre or 0.0))
                    ppgc_ht = round_up_price(prix_apres_remise * current_coeff if current_coeff != 0 else 0.0)
                    ppgc_ttc = round_up_price(ppgc_ht * 1.20)
                    prix_net_net = round_up_price(prix_apres_remise - (prix_apres_remise * current_rfa / 100.0) if current_rfa != 0 else prix_apres_remise)
                    
                    st.write("**Résultats :**")
                    st.write(f"Prix après remise : {prix_apres_remise:.2f}€")
                    st.write(f"PPGC HT : {ppgc_ht:.2f}€")
                    st.write(f"PPGC TTC : {ppgc_ttc:.2f}€")
                    st.write(f"Prix Net Net : {prix_net_net:.2f}€")
        
        # Bouton pour recalculer toutes les valeurs dérivées
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🔄 Recalculer tout", type="primary"):
                # Respect de la priorité : si Remise (%) > 0, on recalcule Remise (€) depuis Prix Brut HT
                st.session_state['selected_articles'] = calculate_derived_values(st.session_state['selected_articles'])
                st.success("✅ Tous les calculs ont été mis à jour!")
                st.rerun()
        
        with col2:
            if st.button("❌ Supprimer tous les articles", type="secondary"):
                st.session_state['selected_articles'] = pd.DataFrame()
                st.session_state['remise_modes'] = {}
                st.rerun()
        
        # Affichage du tableau récapitulatif
        st.subheader("📊 Récapitulatif des articles sélectionnés")
        
        # Recalculer pour l'affichage (garde la priorité au % si non nul)
        display_df = calculate_derived_values(st.session_state['selected_articles'])
        
        # Colonnes à afficher
        display_columns = ['Libellé article', 'Version', 'Code EDI', 'Prix Brut HT',
                           'Remise (%)', 'Remise (€)', 'Prix Net HT', 'Prix net après remise',
                           'Coeff', 'PPGC TTC', 'RFA', 'Prix Net Net']
        
        # Afficher le tableau
        st.dataframe(
            display_df[display_columns].style.format({
                'Prix Brut HT': '{:.2f}€',
                'Remise (%)': '{:.1f}%',
                'Remise (€)': '{:.2f}€',
                'Prix Net HT': '{:.2f}€',
                'Prix net après remise': '{:.2f}€',
                'Coeff': '{:.2f}',
                'PPGC TTC': '{:.2f}€',
                'RFA': '{:.0f}%',
                'Prix Net Net': '{:.2f}€'
            }),
            use_container_width=True
        )
        
        # Résumé & PDF
        st.markdown("### 📊 Résumé de la proposition")
        col1 = st.columns(1)[0]
        total_articles = len(display_df)
        
        with col1:
            st.metric(label="📦 Nombre d'articles", value=total_articles)
        
        st.markdown("---")
        st.subheader("📄 Génération de la proposition")
        
        col1, col2 = st.columns(2)
        
        with col1:
            client_info = st.text_input(
                "👤 Nom du client (optionnel):",
                placeholder="Nom de l'opticien...",
                help="Ce nom apparaîtra sur la proposition PDF"
            )
        
        with col2:
            st.write("")  # Espacements
            st.write("")
            if st.button("📄 Générer la proposition PDF", type="primary", use_container_width=True):
                try:
                    buffer = BytesIO()
                    proposal_number = generate_proposal_number()
                    
                    with st.spinner("Génération du PDF en cours..."):
                        # Recalculer toutes les valeurs dérivées avant de générer le PDF
                        df_for_pdf = calculate_derived_values(st.session_state['selected_articles'])
                        
                        # Passer les modes de remise à la fonction de génération PDF
                        generate_pdf(
                            df_for_pdf, 
                            proposal_number, 
                            buffer, 
                            client_info,
                            st.session_state['remise_modes']
                        )
                    
                    st.success("✅ PDF généré avec succès!")
                    
                    st.download_button(
                        label="📥 Télécharger le PDF",
                        data=buffer.getvalue(),
                        file_name=f"{proposal_number}.pdf",
                        mime="application/pdf",
                        type="primary"
                    )
                except Exception as e:
                    st.error(f"❌ Erreur lors de la génération du PDF: {str(e)}")

if __name__ == "__main__":
    main()
