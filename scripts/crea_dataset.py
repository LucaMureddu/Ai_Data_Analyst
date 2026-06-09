import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Generiamo 2000 righe di vendite realistiche
np.random.seed(42)
date = [datetime(2023, 1, 1) + timedelta(days=np.random.randint(0, 365)) for _ in range(2000)]
prodotti = np.random.choice(["Laptop Pro", "Monitor 27", "Mouse Wireless", "Tastiera Meccanica", "Webcam 4K"], 2000)
nazioni = np.random.choice(["Italia", "Francia", "Germania", "Spagna", "UK"], 2000)
venditori = np.random.choice(["Marco", "Giulia", "Antoine", "Hans", "Elena"], 2000)
costi = np.random.uniform(50, 800, 2000)
ricavi = costi * np.random.uniform(1.2, 2.5, 2000) # Margine del 20-150%

df = pd.DataFrame({
    "Data_Vendita": date,
    "ID_Ordine": [f"ORD-{i+1000}" for i in range(2000)],
    "Venditore": venditori,
    "Nazione": nazioni,
    "Prodotto": prodotti,
    "Costo_Produzione": costi.round(2),
    "Ricavo_Totale": ricavi.round(2)
})

# Esportiamo in Excel!
df.to_excel("vendite_corporate_2023.xlsx", index=False)
print("File Excel 'vendite_corporate_2023.xlsx' generato con successo!")