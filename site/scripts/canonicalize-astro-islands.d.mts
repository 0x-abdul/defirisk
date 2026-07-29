export function canonicalizeAstroIslandUids(html: string): {
  html: string;
  islandCount: number;
};

export function canonicalizeBuildTree(root?: string): Promise<{
  fileCount: number;
  islandCount: number;
}>;
