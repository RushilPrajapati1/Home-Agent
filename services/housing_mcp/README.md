# housing_mcp

housing-mcp is the FastMCP server that prices a specific home: down payment, closing costs, reserves, PITI and PMI (estimate_home_cost), the 30-year rate from FRED MORTGAGE30US cached weekly (get_mortgage_rate), and value and property tax from RentCast (get_property). It has no database access and is one of three services with allowlisted egress, limited to the FRED and RentCast APIs.
