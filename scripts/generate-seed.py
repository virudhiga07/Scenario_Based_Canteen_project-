import json,random,uuid
from datetime import datetime,timedelta,timezone
from pathlib import Path
root=Path(__file__).resolve().parents[1]
rng=random.Random(33)
menu=[]
for i,(n,c,d,p,s,img) in enumerate([
 ('Masala Dosa','Breakfast','Crisp rice crepe, potato masala & coconut chutney',60,32,'dosa'),
 ('Samosa','Snacks','Golden pastry with spiced potato filling',20,8,'samosa'),
 ('Veg Fried Rice','Meals','Wok-tossed rice with seasonal vegetables',80,24,'rice'),
 ('Masala Chai','Beverages','Freshly brewed tea with warming spices',15,65,'chai'),
 ('Idli Sambar','Breakfast','Three soft idlis with sambar & chutney',40,18,'idli'),
 ('Paneer Wrap','Snacks','Spiced paneer, crisp vegetables & mint sauce',70,6,'wrap'),
 ('Veg Thali','Meals','Rice, roti, dal, seasonal sabzi & curd',100,20,'thali'),
 ('Cold Coffee','Beverages','Chilled coffee blended with milk',50,28,'coffee'),
 ('Veg Sandwich','Snacks','Toasted bread, crunchy vegetables & chutney',45,36,'sandwich'),
 ('Fresh Lime Soda','Beverages','Fresh lime, sparkling water & a pinch of salt',30,0,'lime'),
 ('Poha','Breakfast','Light flattened rice with peanuts & curry leaves',35,22,'poha'),
 ('Gulab Jamun','Desserts','Two warm milk dumplings in fragrant syrup',30,16,'dessert')],1):
 menu.append(dict(id=i,name=n,category=c,description=d,price_paise=p*100,stock=s,image=img,active=1))
# Reproducible sample observations over seven days; this is not real college data.
base=datetime(2026,11,15,tzinfo=timezone.utc)
orders=[]
for day,count in enumerate([24,28,22,35,29,39,42]):
 date=base-timedelta(days=6-day)
 for j in range(count):
  ids=rng.choices(range(1,13),weights=[16,20,12,25,10,6,8,13,9,2,5,6],k=rng.randint(1,3))
  quantities={i:ids.count(i)*rng.randint(1,2) for i in set(ids)}
  items=[dict(item_id=i,item_name=menu[i-1]['name'],quantity=q,unit_price_paise=menu[i-1]['price_paise']) for i,q in quantities.items()]
  orders.append(dict(id=str(uuid.uuid5(uuid.NAMESPACE_DNS,f'canteen-demo-{day}-{j}')),customer_name=['Walk-in','Student 033','Student 063','Student 093','Faculty'][j%5],order_type='Takeaway' if j%3==0 else 'Dine-in',payment_method=['UPI','Cash','UPI','Card'][j%4],created_at=(date+timedelta(hours=3,minutes=j*8)).isoformat().replace('+00:00','Z'),total_paise=sum(x['quantity']*x['unit_price_paise'] for x in items),is_demo=1,items=items))
(root/'database/seed.json').write_text(json.dumps({'menu':menu,'orders':orders},indent=2)+'\n')
print(f'Seed: {len(menu)} menu items, {len(orders)} demo orders')
