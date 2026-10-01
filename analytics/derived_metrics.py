import pandas as pd

class DerivedMetricsCalculator:
    def __init__(self, fact_sales: pd.DataFrame, dim_order: pd.DataFrame):
        self.fact_sales = fact_sales
        self.dim_order = dim_order

    def get_gross_revenue(self) -> pd.DataFrame:
        """
        Calculates Gross Revenue per product/date based on TA explicit instructions:
        - Primary Field: total_amount_paid_by_buyer (Total Buyer Payment)
        - Order Status Inclusions: Include strictly Completed orders. Exclude Cancelled or Unpaid.
        """
        # Join with dim_order to filter status
        df = self.fact_sales.merge(self.dim_order[['Order ID', 'Order Status']], on='Order ID', how='left')
        
        # Filter strictly Completed
        df_completed = df[df['Order Status'].str.lower() == 'completed'].copy()
        
        # We assume 'Total Buyer Payment' is the column for total_amount_paid_by_buyer
        df_completed['gross_revenue'] = df_completed['Total Buyer Payment']
        
        return df_completed

    def get_gross_demand(self) -> pd.DataFrame:
        """
        Calculates Gross Demand per product/date based on TA explicit instructions:
        - Demand Calculations: Include both Completed and Returned/Refunded orders.
        - Gross Demand: Count total items ordered using number_of_items (Quantity) before returns.
        """
        df = self.fact_sales.merge(self.dim_order[['Order ID', 'Order Status', 'Return / Refund Status']], on='Order ID', how='left')
        
        status = df['Order Status'].astype('string').str.strip().str.casefold()
        return_status = df['Return / Refund Status'].astype('string').str.strip().str.casefold()
        is_completed = df.get('is_completed', status.eq('completed'))
        is_returned = df.get(
            'is_returned',
            status.isin(['returned', 'refunded'])
            | return_status.isin(['returned', 'refunded', 'request approved', 'dispute resolved']),
        )
        df_demand = df[is_completed.fillna(False) | is_returned.fillna(False)].copy()
        
        df_demand['gross_demand'] = df_demand['Quantity']
        
        return df_demand

    def get_net_revenue_and_inventory(self) -> pd.DataFrame:
        """
        Calculates Net Revenue & Inventory based on TA explicit instructions:
        - Net Revenue & Inventory: Deduct returned quantities using number_of_items_returned 
          (Returned quantity) from total units to reflect realized net sales and restocked inventory.
        """
        df = self.get_gross_revenue()
        
        # Deduct returned quantities
        df['net_quantity'] = df['Quantity'] - df['Returned quantity'].fillna(0)
        
        return df

    def calculate_sales_velocity(self) -> pd.DataFrame:
        """
        Calculates Sales Velocity.
        NOTE: Formula pending TA approval. (Do not invent formulas during coding).
        """
        raise NotImplementedError("Sales Velocity formula is pending TA approval.")

    def calculate_dsi(self) -> pd.DataFrame:
        """
        Calculates 60-day Days Sales of Inventory (DSI).
        NOTE: Formula pending TA approval. (Do not invent formulas during coding).
        """
        raise NotImplementedError("60-day DSI formula is pending TA approval.")

    @staticmethod
    def calculate_stock_out_frequency(stock_history_df: pd.DataFrame) -> pd.DataFrame:
        """Count positive-to-empty stock transitions per product.

        Consecutive empty observations belong to one stock-out event.
        """
        required = {"product_key", "Stock As-Of Date", "Current Stock"}
        missing = required.difference(stock_history_df.columns)
        if missing:
            raise ValueError(f"Missing stock-history columns: {sorted(missing)}")
        stock = stock_history_df.copy()
        stock["Stock As-Of Date"] = pd.to_datetime(stock["Stock As-Of Date"], errors="raise")
        stock["Current Stock"] = pd.to_numeric(stock["Current Stock"], errors="raise")
        stock = stock.sort_values(["product_key", "Stock As-Of Date"])
        previous_stock = stock.groupby("product_key")["Current Stock"].shift(1)
        stock["stock_out_event"] = ((previous_stock > 0) & (stock["Current Stock"] <= 0)).astype(int)
        return (
            stock.groupby("product_key", as_index=False)["stock_out_event"]
            .sum()
            .rename(columns={"stock_out_event": "stock_out_frequency"})
        )

    def calculate_stockout_frequency(self) -> pd.DataFrame:
        """Legacy instance API retained until its input contract is approved."""
        raise NotImplementedError("Stock-Out Frequency formula is pending TA approval.")

