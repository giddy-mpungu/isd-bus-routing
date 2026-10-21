[out:xml][timeout:300][maxsize:536870912];
(
  way["highway"~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|unclassified|residential|living_street|service|road|busway)$"](29.65,-95.50,29.865,-95.27);
);
(._;>;);
out meta;
(
  relation["type"="restriction"](29.65,-95.50,29.865,-95.27);
);
out meta;
