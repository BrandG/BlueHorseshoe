"""Lock the orthogonal factor groups from the signal correlation structure.

Hierarchical clustering on distance = 1 - |corr| over the 31 signals, plus the
participation ratio (effective # of independent factors) from the eigenvalues.
Output = data-driven cluster membership we map to interpretable domain names.
"""
import numpy as np, pandas as pd
from scipy.cluster.hierarchy import linkage, fcluster
from scipy.spatial.distance import squareform

C = pd.read_csv("research/indicator_screen/signal_corr.csv", index_col=0)
C = C.reindex(index=C.columns)          # ensure square/aligned
names = list(C.columns)
A = C.to_numpy(dtype=float)
A = np.nan_to_num((A + A.T) / 2, nan=0.0)
np.fill_diagonal(A, 1.0)

# Participation ratio from eigenvalues of the correlation matrix
ev = np.linalg.eigvalsh(A); ev = np.clip(ev, 0, None)
pr = (ev.sum() ** 2) / (np.square(ev).sum())
print(f"31 signals -> participation ratio = {pr:.2f} effective factors")
print(f"top eigenvalue share = {ev.max()/ev.sum()*100:.0f}% of variance (PC1)\n")

dist = 1 - np.abs(A); np.fill_diagonal(dist, 0.0)
Z = linkage(squareform(dist, checks=False), method="average")
for k in (4, 5, 6):
    labels = fcluster(Z, t=k, criterion="maxclust")
    print(f"==== cut into {k} clusters ====")
    for cl in sorted(set(labels)):
        members = [names[i] for i in range(len(names)) if labels[i] == cl]
        print(f"  C{cl}: {', '.join(members)}")
    print()
