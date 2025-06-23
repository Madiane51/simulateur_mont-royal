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

# Fonction pour encoder une image en base64
def get_base64_image(image_path):
    if os.path.exists(image_path):
        with open(image_path, "rb") as img_file:
            return base64.b64encode(img_file.read()).decode()
    return None

# Fonction pour calculer les valeurs dérivées
def calculate_derived_values(df):
    """Calcule les valeurs dérivées selon les formules Excel"""
    df = df.copy()
    
    # Calcul Prix net après remise (colonne I)
    # =SI(ESTNUM(G2);F2-G2;SI(ESTNUM(H2);F2-H2))
    df['Prix net après remise'] = df.apply(lambda row: 
        row['Prix Net HT'] - row['Remise (€)'] if pd.notna(row['Remise (€)']) and row['Remise (€)'] != 0
        else row['Prix Net HT'] - row['Remise autre (€)'] if pd.notna(row['Remise autre (€)']) and row['Remise autre (€)'] != 0
        else row['Prix Net HT'], axis=1)
    
    # Calcul PPGC HT (colonne K)
    # =I2*J2 (si Coeff est renseigné)
    df['PPGC HT'] = df.apply(lambda row:
        row['Prix net après remise'] * row['Coeff'] if pd.notna(row['Coeff']) and row['Coeff'] != 0
        else row['PPGC HT'] if 'PPGC HT' in df.columns
        else 0, axis=1)
    
    # Calcul PPGC TTC (on ajoute la TVA de 20%)
    df['PPGC TTC'] = df['PPGC HT'] * 1.20
    
    # Calcul Prix Net Net (colonne Q)
    # =I2-(I2*P2) où P2 est en pourcentage
    df['Prix Net Net'] = df.apply(lambda row:
        row['Prix net après remise'] - (row['Prix net après remise'] * row['RFA'] / 100) if pd.notna(row['RFA']) and row['RFA'] != 0
        else row['Prix net après remise'], axis=1)
    
    # Calcul des marges
    df['Marge brute (€)'] = df['PPGC HT'] - df['Prix Net HT']
    df['Marge nette (€)'] = df['PPGC HT'] - df['Prix net après remise']
    
    # Calcul Taux de marque
    df['Taux de marque'] = df.apply(lambda row:
        (row['Marge nette (€)'] / row['PPGC HT']) * 100 if row['PPGC HT'] != 0 else 0, axis=1)
    
    return df

# Fonction pour générer le PDF amélioré (version modifiée)
def generate_pdf(df, proposal_number, buffer, client_info=None):
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
    categories = df['Catégorie produit'].unique()

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

            # Données du tableau - MODIFICATION ICI : Code EDI remplacé par Marge nette
            table_data = [['Libellé article', 'Version', 'Prix Net HT', 'Remise (€)', 'Prix après remise', 'PPGC TTC', 'Marge nette', 'RFA', 'Prix Net Net']]
            
            for _, row in cat_df.iterrows():
                # Gestion du wrapping pour les libellés longs
                libelle_para = Paragraph(str(row['Libellé article']), styles['Normal'])
                table_data.append([
                    libelle_para,
                    str(row['Version']),
                    f"{row['Prix Net HT']:.2f}€",
                    f"{row['Remise (€)']:.2f}€" if pd.notna(row['Remise (€)']) else "-",
                    f"{row['Prix net après remise']:.2f}€",
                    f"{row['PPGC TTC']:.2f}€",
                    f"{row['Marge nette (€)']:.2f}€",  # NOUVELLE COLONNE : Marge nette
                    f"{row['RFA']:.0f}%" if pd.notna(row['RFA']) else "-",
                    f"{row['Prix Net Net']:.2f}€"
                ])

            # Création du tableau avec largeurs adaptées - MODIFICATION DES LARGEURS
            table = Table(table_data, colWidths=[3.5*cm, 2*cm, 2*cm, 2*cm, 2.7*cm, 2*cm, 2*cm, 1.5*cm, 2*cm])
            table.setStyle(TableStyle([
                # En-tête
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#f68b1f")),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 9),
                ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
                ('VALIGN', (0, 0), (-1, 0), 'MIDDLE'),
                
                # Corps du tableau
                ('BACKGROUND', (0, 1), (-1, -1), colors.white),
                ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
                ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 1), (-1, -1), 8),
                ('ALIGN', (0, 1), (-1, -1), 'CENTER'),
                ('VALIGN', (0, 1), (-1, -1), 'MIDDLE'),
                
                # Bordures
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('LINEBELOW', (0, 0), (-1, 0), 2, colors.HexColor("#f68b1f")),
                
                # Alternance de couleurs
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

    # Construction du PDF
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
    numeric_columns = ['Prix Brut HT', 'Prix Net HT', 'Remise (€)', 'Remise autre (€)', 
                      'Prix net après remise', 'Coeff', 'PPGC HT', 'PPGC TTC', 
                      'Marge brute (€)', 'Marge nette (€)', 'Taux de marque', 'RFA', 'Prix Net Net']
    
    for col in numeric_columns:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    
    return df

# Fonction pour valider les colonnes
def validate_dataframe(df):
    """Valide que le DataFrame contient les colonnes essentielles"""
    essential_columns = [
        'Catégorie produit', 'Libellé article', 'Version', 'Code EDI', 'Prix Net HT'
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
        gb.configure_selection("multiple", use_checkbox=True, groupSelectsChildren=True)
        gb.configure_grid_options(domLayout='normal')
        gb.configure_default_column(enablePivot=True, enableValue=True, enableRowGroup=True)
        
        # Mise en forme des colonnes
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
        
        st.info("💡 Vous pouvez modifier les colonnes Remise (€), Coeff, RFA pour appliquer des conditions commerciales spécifiques")
        
        # Interface d'édition
        modified_articles = st.session_state['selected_articles'].copy()
        
        # Créer des colonnes pour l'édition
        for idx, row in modified_articles.iterrows():
            with st.expander(f"📝 {row['Libellé article']} - {row['Version']}", expanded=False):
                col1, col2, col3, col4 = st.columns(4)
                
                with col1:
                    st.write(f"**Prix Net HT:** {row['Prix Net HT']:.2f}€")
                    remise = st.number_input(
                        "Remise (€)",
                        min_value=0.0,
                        value=float(row['Remise (€)']),
                        step=0.1,
                        key=f"remise_{idx}",
                        help="Remise en euros à appliquer"
                    )
                    modified_articles.loc[idx, 'Remise (€)'] = remise
                
                with col2:
                    coeff = st.number_input(
                        "Coefficient",
                        min_value=0.0,
                        value=float(row['Coeff']) if row['Coeff'] != 0 else 1.0,
                        step=0.1,
                        key=f"coeff_{idx}",
                        help="Coefficient multiplicateur pour le PPGC"
                    )
                    modified_articles.loc[idx, 'Coeff'] = coeff
                
                with col3:
                    rfa = st.number_input(
                        "RFA (%)",
                        min_value=0.0,
                        max_value=100.0,
                        value=float(row['RFA']),
                        step=1.0,
                        key=f"rfa_{idx}",
                        help="Pourcentage RFA à appliquer"
                    )
                    modified_articles.loc[idx, 'RFA'] = rfa
                
                with col4:
                    # Calcul en temps réel
                    prix_apres_remise = row['Prix Net HT'] - remise
                    ppgc_ht = prix_apres_remise * coeff if coeff != 0 else 0
                    ppgc_ttc = ppgc_ht * 1.2
                    prix_net_net = prix_apres_remise - (prix_apres_remise * rfa / 100)
                    
                    st.write("**Résultats:**")
                    st.write(f"Prix après remise: {prix_apres_remise:.2f}€")
                    st.write(f"PPGC HT: {ppgc_ht:.2f}€")
                    st.write(f"PPGC TTC: {ppgc_ttc:.2f}€")
                    st.write(f"Prix Net Net: {prix_net_net:.2f}€")
        
        # Bouton pour appliquer les modifications
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🔄 Appliquer les modifications", type="primary"):
                # Recalculer toutes les valeurs dérivées
                st.session_state['selected_articles'] = calculate_derived_values(modified_articles)
                st.success("✅ Modifications appliquées avec succès!")
                st.rerun()
        
        with col2:
            if st.button("❌ Supprimer tous les articles", type="secondary"):
                st.session_state['selected_articles'] = pd.DataFrame()
                st.rerun()

        # Affichage du tableau récapitulatif
        st.subheader("📊 Récapitulatif des articles sélectionnés")
        
        # Recalculer pour l'affichage
        display_df = calculate_derived_values(st.session_state['selected_articles'])
        
        # Colonnes à afficher
        display_columns = ['Libellé article', 'Version', 'Code EDI', 'Prix Net HT', 
                          'Remise (€)', 'Prix net après remise', 'Coeff', 'PPGC TTC', 'RFA', 'Prix Net Net']
        
        # Afficher le tableau
        st.dataframe(
            display_df[display_columns].style.format({
                'Prix Net HT': '{:.2f}€',
                'Remise (€)': '{:.2f}€',
                'Prix net après remise': '{:.2f}€',
                'Coeff': '{:.2f}',
                'PPGC TTC': '{:.2f}€',
                'RFA': '{:.0f}%',
                'Prix Net Net': '{:.2f}€'
            }),
            use_container_width=True
        )

        # Calculs et résumé
        total_articles = len(display_df)
        total_prix_net_net = display_df['Prix Net Net'].sum()
        total_ppgc_ttc = display_df['PPGC TTC'].sum()
        
        # Affichage des métriques
        st.markdown("### 📊 Résumé de la proposition")
        
        # col1, col2, col3 = st.columns(3)
        col1 = st.columns(1)[0]
        
        with col1:
            st.metric(
                label="📦 Nombre d'articles",
                value=total_articles
            )
        
        # with col2:
        #     st.metric(
        #         label="💰 Total PPGC TTC",
        #         value=f"{total_ppgc_ttc:.2f}€"
        #     )
        
        # with col3:
        #     st.metric(
        #         label="💳 Total Prix Net Net",
        #         value=f"{total_prix_net_net:.2f}€"
        #     )

        # Génération du PDF
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
            st.write("")  # Espacement
            st.write("")  # Espacement
            
            if st.button("📄 Générer la proposition PDF", type="primary", use_container_width=True):
                try:
                    buffer = BytesIO()
                    proposal_number = generate_proposal_number()
                    
                    with st.spinner("Génération du PDF en cours..."):
                        generate_pdf(st.session_state['selected_articles'], proposal_number, buffer, client_info)
                    
                    st.success("✅ PDF généré avec succès!")
                    
                    # Bouton de téléchargement
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