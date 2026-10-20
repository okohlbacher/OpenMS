#include <OpenMS/FORMAT/XMLFile.h>
#include <OpenMS/FORMAT/HANDLERS/XMLHandler.h>
#include <iostream>
struct R:OpenMS::Internal::XMLFile {using XMLFile::parseBuffer_;using XMLFile::enforceEncoding_;};
struct H:OpenMS::Internal::XMLHandler{H():XMLHandler("memory","1"){};std::u16string text;void onCharacters(const char16_t*c,OpenMS::Size n)override{text.append(c,n);}};
int main(){bool ok=true;for(bool ns:{false,true})for(const char* decl:{"UTF-8","X-BOGUS","UTF-16"}){R r;H h;r.enforceEncoding_("ISO-8859-1");try{r.parseBuffer_(std::string("<?xml version='1.0' encoding='")+decl+"'?><r>\xe4</r>",&h,ns);bool pass=h.text==u"ä";std::cout<<"mode="<<ns<<" decl="<<decl<<" text_matches="<<pass<<"\n";ok&=pass;}catch(std::exception&e){std::cout<<"mode="<<ns<<" decl="<<decl<<" REJECT "<<e.what()<<"\n";ok=false;}}return ok?0:1;}
