import imaplib 
import email
import datetime
from selenium  import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as ec
import os
import database_manager as dbman

class orderFromEmail:
    def __init__(self, **kwargs):
        self.email = kwargs['email']
        self.host = kwargs['host']
        self.port = kwargs['port']
        self.password = kwargs['password']
        self.dbName = 'orderDB.db'

        #Assure that the sqlite3 data base exists 
        if os.path.exists(self.dbName) is False:
            dbman.createDB(self.dbName)
    
    def EmailConnect(self):
        #Perform both the conenction and the user login
        #con = imaplib.IMAP4_SSL(host = "imap.gigahost.dk", port = 993)
        self.connection = imaplib.IMAP4_SSL(host = self.host, port = self.port)
        self.connection.login(user = self.email, password = self.password)

    def EmailFolderSelect(self, folderName):
        '''
        folderName is a string e.g. INBOX. Herafter the focus will be of all the emails in INBOX folder.
        '''
        self.connection.select(folderName)

    def searchOrderEmail(self, emailFrom, **kwargs):
        '''
        looks into kontakt@dimsum.dk for new emails from shopify containing the order. The order
        number is compared against current existing numbers in data base. If the order number does 
        not currently exists, it will be inserted into the data. The delivery date and time is found
        through browser automation into the shopify account. 
        '''
        #Look into the sqlite data base and look for existing orders
        orderno_db = dbman.get_existingOrderNo(self.dbName)
        
        #Get today's date stamp
        today = datetime.datetime.today()
        today = today.strftime('%d-%b-%Y')

        today = '21-Mar-2020' # FIXME: FOR TESTING ONLY REMEMBER TO REMOVE

        #Perform a filter to search for all the emails from emailFrom from the date starting from today
        result, mailid_from = self.connection.search(None, f'(FROM "{emailFrom}")')

        if result != 'OK':
            print(f'No incoming emails from {emailFrom}')
            self.logoutClose()
            return
        
        #There exists emails from the sender. Check if any emails received from today
        result, mailid_since = self.connection.search(None, f'(SINCE "{today}")')
        if result != 'OK':
            print(f'Email from {emailFrom} exists, but none of these emails are from today!')
            self.logoutClose()
            return
        
        #Find the common ids to include both from sender and received date as today
        mailid_from = mailid_from[0].split()
        mailid_since = mailid_since[0].split()
        mail_id = set(mailid_from).intersection(set(mailid_since))

        #Fetch the emails from the common mail id in a loop. Note, the filter so far only searched for sender from today. Still need to assure that the mail type is a order mail
        OrderList = list()

        for mailid in mail_id:
            #Get email data
            result, data = self.connection.fetch(mailid, '(RFC822)')

            msg = email.message_from_bytes(data[0][1])

            #get subject title
            msg_subject = msg['Subject']

            #decode
            msg_subject = email.header.decode_header(msg_subject)

            if msg_subject[0][1] != None:
                msg_subject = msg_subject[0][0].decode(msg_subject[0][1])
            else:
                msg_subject = msg_subject[0][0]
            
            #Look for the selective tag in the subject field that is specific for a order email
            if '[Hidden Dimsum Delivery Take Away] Order #' in msg_subject:
                orderno, guestName = self.get_SubjectInfo(msg_subject)

                #If orderno already exists, no need to do browser automation
                if int(orderno) in orderno_db:
                    continue

                newOrder = dict()
                newOrder['ShopifyOrderNo'] = orderno
                newOrder['guestName'] = guestName

                #Extract email body information
                for part in msg.walk():
                    if part.get_content_type() == 'text/plain':
                        bodyText = part.get_payload(decode = True)
                        bodyText = bytes.decode(bodyText, encoding='utf-8')
                        #Get item related information
                        itemName, amount, price = self.get_itemInfo(bodyText)
                        newOrder['itemName'] = itemName
                        newOrder['amount'] = [int(i) for i in amount]
                        tmp = list()
                        for i in price:
                            tmp.append(float(i.replace(',','.')))
                            newOrder['price'] = tmp

                        #Get delivery method
                        deliveryMethod = self.get_deliveryMethod(bodyText)
                        newOrder['deliveryMethod'] = deliveryMethod

                        #Get address if delivery
                        if deliveryMethod == 'Delivery':
                            addrStreet, city = self.get_address(bodyText)
                            newOrder['deliverAddress'] = addrStreet + ', ' + city
                    
                        #Get contact information being either phone or email
                        contact = self.get_contactMethod(bodyText)
                        newOrder['contact'] = contact
                    
                        #Get the order link
                        self.get_orderLink(bodyText)
                        newOrder['orderLink'] = self.get_orderLink(bodyText)

                        #Do a browswer automation to get delivery date and time
                        date, timestamp = self.deliveryTimeStamp(newOrder['orderLink'])
                        newOrder['ExecutionDate'] = date
                        newOrder['ExecutionTime'] = timestamp
             
            OrderList.append(newOrder)
        self.logoutClose()
        return OrderList

    def deliveryTimeStamp(self, https_link):
        '''
        Runs selenium in headless mode to obtain the date and time stamp for either pickup or delivery
        '''

        chrome_options = Options()
        chrome_options.headless = True
        #chrome_options.add_experimental_option("detach", False)
        chrome_options.add_argument("--window-size=1920x1080")
        currentPath = os.getcwd()
        driverpath = os.path.join(currentPath, "headless_chrome", "chromedriver")

        driver = webdriver.Chrome(chrome_options = chrome_options, executable_path=driverpath)
        driver.get(https_link)
        print('browser initiated in hidden mode')
        wait = WebDriverWait(driver, 30)
        wait.until(ec.visibility_of_element_located(
            (By.XPATH, '//*[@id="body-content"]/div[1]/div[2]/div/form/button'),
            ))

        #Login
        elem = driver.find_element_by_xpath('//*[@id="account_email"]')
        elem.send_keys("jian_dfh@hotmail.com")
        wait.until(ec.element_to_be_clickable((By.XPATH, '/html/body/div[1]/div[2]/div/form/button'),)).click()

        wait.until(ec.visibility_of_element_located(
            (By.XPATH, '//*[@id="account_password"]')
        )).send_keys("PASSport1")
        wait.until(ec.element_to_be_clickable(
            (By.XPATH, '//*[@id="login_form"]/button'),
        )).click()

        print('Logging into Shopify')
        #Locate the Delivery date and time frame
        wait.until(ec.visibility_of_element_located(
            (By.XPATH, '//*[@id="note-attributes"]/div[2]/div[2]/div/div[3]/div'),
        ))

        date = driver.find_element_by_xpath('//*[@id="note-attributes"]/div[2]/div[2]/div/div[3]/div').text

        wait.until(ec.visibility_of_element_located((By.XPATH, '//*[@id="note-attributes"]/div[2]/div[2]/div/div[4]/div'),))
        timeframe = driver.find_element_by_xpath('//*[@id="note-attributes"]/div[2]/div[2]/div/div[4]/div').text
        print('Obtained date and time')
        print('Complete browser closed!')
        return date, timeframe

    def get_orderLink(self, bodyText):
        textlines = bodyText.splitlines()
        for item in textlines:
            if item.startswith('( https://'):
                #Strip the () from the link
                item = item[1 : -2].strip()
                return item


    def get_contactMethod(self, bodyText):
        textsplit = bodyText.splitlines()
        #The contact information is in the last time
        contact = [i for i in textsplit if i][-1]
        return contact

    def get_address(self, bodyText):
        '''
        takes the bodyText as input, and returns address as two components in str, first being street and number and second being city
        '''
        textsplit = bodyText.splitlines()
        #Remove everything before shipping address
        index = textsplit.index('Shipping address:')
        del textsplit[0 : index + 1]
        #remove the first next text occurence which is guestName
        for item in enumerate(textsplit):
            if item[1]:
                index = item[0]
                break
        del textsplit[0 : index+1]

        #Now the next occurence of text is the address street and the subsequent is the city
        for item in enumerate(textsplit):
            if item[1]:
                addrStreet = item[1]
                index = item[0]
                break

        del textsplit[0 : index + 1]

        for item in textsplit:
            if item:
                city = item
                #Post code first followed by city
                city = city.split(',')
                city = city[1].strip() + ', ' + city[0].strip()
                break

        return addrStreet, city

    def get_deliveryMethod(self, bodyText):
        '''
        read from the shopify order email the delivery method that is either store pickup or delivery and returns the method as a str
        '''
        textsplit = bodyText.splitlines()
        readstart = False
        for item in textsplit:
            if item == 'Delivery method:':
                readstart = True
                continue

            if readstart is True and item:
                return item.strip()
    
    def get_SubjectInfo(self, subject_title):
        orderno = subject_title.split(sep='#')[1].split()[0]
        guestName = subject_title.split(sep = 'placed by ')[1]
        return orderno, guestName
    
    def get_itemInfo(self, bodyText):
        '''
        extract amount, item name and unit price based on get_payload(). All extrated parameters returned in str
        '''
        textsplit = bodyText.splitlines()
        itemReadStart = False
        itemName = list()
        amount = list()
        price = list()

        for item in textsplit:
            #Define when to start reading
            if item == '*':
                itemReadStart = True
                continue

            #Extract itemName, amount and price
            if itemReadStart == True and item:
                amount.append(item.split('x', 1)[0].strip())
                tmp = item.split('x', 1)[1].split(' for ')
                itemName.append(tmp[0].strip())
                price.append(tmp[1].strip().split('kr each')[0].strip())
                itemReadStart = False
        
        return itemName, amount, price
    
    def logoutClose(self):
        self.connection.close()
        self.connection.logout()


order = orderFromEmail(email = 'kontakt@dimsum.dk', host = 'imap.gigahost.dk', password = 'DimSum2018', port = 993)
order.EmailConnect()
order.EmailFolderSelect(folderName = 'INBOX')
orderList = order.searchOrderEmail('kontakt@dimsum.dk')
print(orderList)
dbman.insert_orderList_to_DB('orderDB.db', orderList)